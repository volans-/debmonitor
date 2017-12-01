#!/usr/bin/env python
# ----------------------------------------------------------------------------
# DebMonitor CLI - Debian packages tracker CLI
# Copyright (C) 2017-2018  Riccardo Coccioli <rcoccioli@wikimedia.org>
#                          Wikimedia Foundation, Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
# ----------------------------------------------------------------------------
"""
DebMonitor CLI - Debian packages tracker CLI.

Automatically collect the current status of all installed and upgradable packages and report it to a DebMonitor server.
It can report all installed and upgradable packages, just the upgradable ones, or the changes reported by a Dpkg hook.

This script was tested with Python 2.7, 3.5, 3.6.

* Install the following Debian packages dependencies, choosing either the Python2 or the Python3 variant based on which
  version of Python will be used to run this script:

  * python-apt
  * python-requests

* Deploy this standalone CLI script across the fleet, for example into ``/usr/local/bin/debmonitor``, and make it
  executable, optionally modifying the shebang to force a specific Python version.
* Add a configuration file in ``/etc/apt/apt.conf.d/`` with the following content, replacing ``##DEMBONITOR_SERVER##``
  with the domain name at which the DebMonitor server is reachable.

  .. code-block:: none

    # Tell dpkg to use version 3 of the protocol for the Pre-Install-Pkgs hook (version 2 is also supported)
    Dpkg::Tools::options::/usr/local/bin/debmonitor::Version "3";
    # Set the dpkg hook to call DebMonitor for any change with the -g/--dpkg option to read the changes from stdin
    Dpkg::Pre-Install-Pkgs {"/usr/local/bin/debmonitor -s ##DEMBONITOR_SERVER## -g || true";};
    # Set the APT update hook to call DebMonitor with the -u/upgradable option to send only the pending upgrades
    APT::Update::Post-Invoke {"/usr/local/bin/debmonitor -s ##DEMBONITOR_SERVER## -u || true"};

* Set a daily or weekly crontab that executes DebMonitor to send the list of all installed and upgradable packages
  (do not set the ``-g`` or ``-u`` options). It is used as a reconciliation method if any of the hook would fail.
  It is also required to run DebMonitor in full mode at least once to track all the packages.

"""
from __future__ import print_function

import argparse
import json
import logging
import platform
import socket
import sys

from collections import namedtuple

import apt
import requests


__version__ = '1.0.0'

logger = logging.getLogger('debmonitor')
AptLineV2 = namedtuple('LineV2', ['name', 'version_from', 'direction', 'version_to', 'action'])
AptLineV3 = namedtuple('LineV3', ['name', 'version_from', 'arch_from', 'multiarch_from', 'direction', 'version_to',
                                  'arch_to', 'multiarch_to', 'action'])


class AptInstalledFilter(apt.cache.Filter):
    """Filter class for python-apt to filter only installed packages."""

    def apply(self, pkg):
        """Filter only installed packages.

        :Parameters:
            according to parent `apply` method.

        Returns:
            bool: True if the package is installed, False otherwise.
        """
        if pkg.is_installed:
            return True

        return False


def get_packages(upgradable_only=False):
    """Return the list of installed and upgradable packages, or only the upgradable ones.

    Arguments:
        upgradable_only (bool, optional): whether to return only the upgradable packages.

    Returns:
        dict: a dictionary of lists with the installed and upgradable packages.
    """
    packages = {'installed': [], 'upgradable': [], 'uninstalled': []}
    cache = apt.cache.FilteredCache()
    cache.set_filter(AptInstalledFilter())
    logger.info('Found %d installed binary packages', len(cache))

    cache.upgrade(dist_upgrade=True)
    upgrades = cache.get_changes()
    logger.info('Found %d upgradable binary packages (including new dependencies)', len(upgrades))

    if not upgradable_only:
        for pkg in cache:
            package = {'name': pkg.name, 'version': pkg.installed.version, 'source': pkg.installed.source_name}
            packages['installed'].append(package)
            logger.debug('Collected installed: %s', package)

    for pkg in upgrades:
        if not pkg.is_installed:
            continue

        upgrade = {'name': pkg.name, 'version_from': pkg.installed.version, 'version_to': pkg.candidate.version,
                   'source': pkg.candidate.source_name}
        packages['upgradable'].append(upgrade)
        logger.debug('Collected upgrade: %s', upgrade)

    return packages


def parse_dpkg_hook(input_lines):
    """Parse packages changes as reported by the Dpkg::Pre-Install-Pkgs hook.

    Arguments:
        input_lines (list): list of strings with the Dpkg::Pre-Install-Pkgs hook output.

    Returns:
        dict: a dictionary of lists with the installed and uninstalled packages.

    Raises:
        RuntimeError: if the version of the Dpkg::Pre-Install-Pkgs hook protocol is not supported or unable to
            determine its version.

    """
    hook_version_line = input_lines.pop(0).strip()

    if not hook_version_line.startswith('VERSION '):
        raise RuntimeError('Expected VERSION line to be the first one, got: {ver}'.format(ver=hook_version_line))

    hook_version = int(hook_version_line[-1])
    if hook_version not in (2, 3):
        raise RuntimeError('Unsupported version {ver}'.format(ver=hook_version))

    try:
        upgrades = input_lines[input_lines.index('\n') + 1:]
    except ValueError:
        raise RuntimeError('Unable to find the empty line separator in input')

    if not upgrades:
        return {}

    packages = {'installed': [], 'upgradable': [], 'uninstalled': []}
    cache = apt.cache.Cache()
    for update_line in upgrades:
        group, package = parse_apt_line(update_line, cache, version=hook_version)
        if group is not None:
            packages[group].append(package)

    logger.info('Got %d updates from dpkg hook version %d', len(packages['installed']) + len(packages['uninstalled']),
                hook_version)

    return packages


def parse_apt_line(update_line, cache, version=3):
    """Parse a single package line as reported by the Dpkg::Pre-Install-Pkgs hook version 3 or 2.

    - Protocol version 2 examples
      - Installation
        package-name - < 1.0.0-1 /var/cache/apt/archives/package-name_1.0.0-1_all.deb
        package-name - < 1.0.0-1 **CONFIGURE**

      - Re-installation
        package-name 1.0.0-1 = 1.0.0-1 /var/cache/apt/archives/package-name_1.0.0-1_all.deb
        package-name 1.0.0-1 = 1.0.0-1 **CONFIGURE**

      - Upgrade
        package-name 1.0.0-1 < 1.0.0-2 /var/cache/apt/archives/package-name_1.0.0-2_all.deb
        package-name 1.0.0-1 < 1.0.0-2 **CONFIGURE**

      - Downgrade
        package-name 1.0.0-2 > 1.0.0-1 /var/cache/apt/archives/package_name_.1.0.0-1_all.deb
        package-name 1.0.0-2 > 1.0.0-1 **CONFIGURE**

      - Removal
        package-name 1.0.0-1 > - **REMOVE**

    - Protocol version 3 examples
      - Installation
        package-name - - none < 1.0.0-1 all none /var/cache/apt/archives/package-name_1.0.0-1_all.deb
        package-name - - none < 1.0.0-1 all none **CONFIGURE**

      - Re-installation
        package-name 1.0.0-1 all none = 1.0.0-1 all none /var/cache/apt/archives/package-name_1.0.0-1_all.deb
        package-name 1.0.0-1 all none = 1.0.0-1 all none **CONFIGURE**

      - Upgrade
        package-name 1.0.0-1 all none < 1.0.0-2 all none /var/cache/apt/archives/package-name_1.0.0-2_all.deb
        package-name 1.0.0-1 all none < 1.0.0-2 all none **CONFIGURE**

      - Downgrade
        package-name 1.0.0-2 all none > 1.0.0-1 all none /var/cache/apt/archives/package_name_.1.0.0-1_all.deb
        package-name 1.0.0-2 all none > 1.0.0-1 all none **CONFIGURE**

      - Removal
        package-name 1.0.0-2 all none > - - none **REMOVE**

    Arguments:
        update_line (str): one line of the Dpkg::Pre-Install-Pkgs hook output.
        cache (apt.cache.Cache): a `apt.cache.Cache` instance to gather additional metadata of the modified packages.
        version (int, optional): the Dpkg::Pre-Install-Pkgs hook protocol version. Supported versions are: 2, 3.

    Returns:
        tuple: a tuple (str, dict) with the name of the group the package belongs to and the dictionary with the
            package metadata. The group is one of 'installed', 'uninstalled'.

    Raises:
        RuntimeError: if the version of the Dpkg::Pre-Install-Pkgs hook protocol is not supported.

    """
    if version == 3:
        line = AptLineV3(*update_line.strip().split(' ', 9))
    elif version == 2:
        line = AptLineV2(*update_line.strip().split(' ', 5))
    else:
        raise RuntimeError('Unsupported version {ver}'.format(ver=version))

    if line.action in ('**CONFIGURE**'):  # Skip those lines, package already tracked
        return None, None

    cache_item = cache[line.name]
    if line.direction == '<':  # Upgrade
        group = 'installed'
        package = {'name': line.name, 'version': line.version_to, 'source': cache_item.candidate.source_name}

        if line.version_from == '-':
            action = 'installed'
        else:
            action = 'upgraded'
        logger.debug('Collected %s package: %s', action, package)

    elif line.direction == '>':  # Downgrade/removal
        if line.version_to == '-':  # Removal
            group = 'uninstalled'
            package = {'name': line.name, 'version': line.version_from, 'source': cache_item.installed.source_name}
            logger.debug('Collected removed package: %s', package)
        else:  # Downgrade
            group = 'installed'
            package = {'name': line.name, 'version': line.version_to, 'source': cache_item.candidate.source_name}
            logger.debug('Collected downgraded package: %s', package)

    else:  # No change (=)
        group = None
        package = None

    return group, package


def parse_args(argv):
    """Parse command line arguments.

    Arguments:
        argv (list): list of strings with the CLI parameters to parse.

    Returns:
        argparse.Namespace: the parsed CLI parameters.

    Raises:
        SystemExit: if there are missing required parameters or an invalid combination of parameters is used.

    """
    parser = argparse.ArgumentParser(prog='debmonitor', description='DebMonitor CLI - Debian packages tracker CLI',
                                     epilog=__doc__)
    parser.add_argument('-s', '--server', help='DebMonitor server DNS name, required unless -n/--dry-run is set.')
    parser.add_argument('-p', '--port', default=443, type=int,
                        help='Port in which the DebMonitor server is listening. [default: 443]')
    parser.add_argument('-c', '--cert',
                        help=('Path to the client SSL certificate to use for sending the update. If it does not '
                              'contain also the private key, -k/--key must be specified too.'))
    parser.add_argument('-k', '--key',
                        help=('Path to the client SSH private key to use for sending the update. If not specified, '
                              'the private key is expected to be found in the certificate defined by -c/--cert.'))
    parser.add_argument('-a', '--api', help='Version of the API to use', default='v1')
    parser.add_argument('-u', '--upgradable', action='store_true',
                        help='Send only the list of upgradable packages. Can be used as a hook for apt-get update.')
    parser.add_argument('-g', '--dpkg-hook', action='store_true',
                        help=('Parse modified packages from stdin according to DPKG hook Dpkg::Pre-Install-Pkgs '
                              'format for version 3 and 2.'))
    parser.add_argument('-n', '--dry-run', action='store_true',
                        help='Do not send the report to DebMonitor server and print it to stdout.')
    parser.add_argument('-d', '--debug', action="store_true", help='Set logging level to DEBUG')
    parser.add_argument('--version', action='version', version='%(prog)s {version}'.format(version=__version__))
    args = parser.parse_args(argv)

    if not args.server and not args.dry_run:
        parser.error('argument -s/--server is required unless -n/--dry-run is set')

    if args.key is not None and args.cert is None:
        parser.error('argument -c/--cert is required when -k/--key is set')

    if args.upgradable and args.dpkg_hook:
        parser.error('argument -u/--upgradable and -g/--dpkg-hook are mutually exclusive')

    return args


def run(args, input_lines=None):
    """Collect the list of packages and send the update to the DebMonitor server.

    Arguments:
        args (argparse.Namespace): the parsed CLI parameters.

    Raises:
        RuntimeError, requests.exceptions.RequestException: on error.

    """
    hostname = socket.getfqdn()

    if args.upgradable or args.dpkg_hook:
        upgrade_type = 'partial'
    else:
        upgrade_type = 'full'

    if args.dpkg_hook:
        packages = parse_dpkg_hook(input_lines)
    else:
        packages = get_packages(upgradable_only=args.upgradable)

    if sum(len(i) for i in packages.values()) == 0:  # No packages to report
        return

    payload = {
        'api_version': args.api,
        'os': platform.linux_distribution()[0].title(),
        'hostname': hostname,
        'running_kernel': {
            'release': platform.release(),
            'version': platform.version(),
        },
        'installed': packages['installed'],
        'uninstalled': packages['uninstalled'],
        'upgradable': packages['upgradable'],
        'update_type': upgrade_type,
    }

    if args.dry_run:
        print(json.dumps(payload, sort_keys=True, indent=4))
        return

    url = 'https://{server}:{port}/hosts/{host}/update'.format(server=args.server, port=args.port, host=hostname)

    cert = None
    if args.key is not None:
        cert = (args.cert, args.key)
    elif args.cert is not None:
        cert = args.cert

    response = requests.post(url, cert=cert, json=payload)
    if response.status_code != requests.status_codes.codes.created:
        raise RuntimeError('Failed to send the update to the DebMonitor server: {status} {body}'.format(
            status=response.status_code, body=response.text))
    logger.info('Successfully sent the %s update to the DebMonitor server', upgrade_type)


def main(args, input_lines=None):
    """Run the DebMonitor CLI.

    Arguments:
        args (argparse.Namespace): the parsed CLI parameters.
        input_lines (list, optional): input lines from stdin when the -g/--dpkg-hook option is set.

    Returns:
        int: the exit code of the operation. Zero on success, a positive integer on failure.
    """
    level = logging.INFO
    if args.debug:
        level = logging.DEBUG
    logging.basicConfig(level=level)

    try:
        run(args, input_lines=input_lines)
        exit_code = 0
    except Exception as e:
        exit_code = 1
        message = 'Failed to execute DebMonitor CLI: '
        if args.debug:
            logger.exception(message)
        else:
            logger.error(message + str(e))

    return exit_code


if __name__ == '__main__':  # pragma: no cover
    args = parse_args(sys.argv[1:])
    input_lines = None
    if args.dpkg_hook:
        input_lines = sys.stdin.readlines()

    sys.exit(main(args, input_lines=input_lines))