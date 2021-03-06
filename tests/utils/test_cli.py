import json
import os
import sys

from collections import namedtuple
from unittest.mock import MagicMock, mock_open, patch

import pytest

OS_NAME = 'ExampleOS'
KERNEL_RELEASE = '1.0.0'
KERNEL_VERSION = 'ExampleOS v1.0.0-1'
mocked_apt = MagicMock()
mocked_apt.cache.Filter = object
mocked_lsb = MagicMock()
mocked_lsb.get_distro_information().get.return_value = OS_NAME
mocked_platform = MagicMock()
mocked_platform.release.return_value = KERNEL_RELEASE
mocked_platform.version.return_value = KERNEL_VERSION
with patch.dict(sys.modules, {'apt': mocked_apt, 'lsb_release': mocked_lsb, 'platform': mocked_platform}):
    from utils import cli


AptPackage = namedtuple('AptPackage', ['name', 'is_installed', 'installed', 'candidate'])
AptPkgVersion = namedtuple('AptPkgVersion', ['source_name', 'version'])
HOSTNAME = 'host1.example.com'
DEBMONITOR_SERVER = 'debmonitor.example.com'
DEBMONITOR_BASE_URL = 'https://{server}:443'.format(server=DEBMONITOR_SERVER)
DEBMONITOR_UPDATE_URL = '{base_url}/hosts/{hostname}/update'.format(base_url=DEBMONITOR_BASE_URL, hostname=HOSTNAME)
DEBMONITOR_CLIENT_URL = '{base_url}/client'.format(base_url=DEBMONITOR_BASE_URL)
DEBMONITOR_CLIENT_VERSION = '0.0.1'
DEBMONITOR_CLIENT_CHECKSUM = '8d777f385d3dfec8815d20f7496026dc'
APT_HOOK_LINES = {
    2: [
        # Installed
        'package-name - < 1.0.0-1 /var/cache/apt/archives/package-name_1.0.0-1_all.deb\n',
        'package-name - < 1.0.0-1 **CONFIGURE**\n',
        # Re-installed
        'package-name 1.0.0-1 = 1.0.0-1 /var/cache/apt/archives/package-name_1.0.0-1_all.deb\n',
        'package-name 1.0.0-1 = 1.0.0-1 **CONFIGURE**\n',
        # Upgraded
        'package-name 1.0.0-1 < 1.0.0-2 /var/cache/apt/archives/package-name_1.0.0-2_all.deb\n',
        'package-name 1.0.0-1 < 1.0.0-2 **CONFIGURE**\n',
        # Downgraded
        'package-name 1.0.0-2 > 1.0.0-1 /var/cache/apt/archives/package_name_.1.0.0-1_all.deb\n',
        'package-name 1.0.0-2 > 1.0.0-1 **CONFIGURE**\n',
        # Removed
        'package-name 1.0.0-1 > - **REMOVE**\n',
    ],
    3: [
        # Installed
        'package-name - - none < 1.0.0-1 all none /var/cache/apt/archives/package-name_1.0.0-1_all.deb\n',
        'package-name - - none < 1.0.0-1 all none **CONFIGURE**\n',
        # Re-installed
        'package-name 1.0.0-1 all none = 1.0.0-1 all none /var/cache/apt/archives/package-name_1.0.0-1_all.deb\n',
        'package-name 1.0.0-1 all none = 1.0.0-1 all none **CONFIGURE**\n',
        # Upgraded
        'package-name 1.0.0-1 all none < 1.0.0-2 all none /var/cache/apt/archives/package-name_1.0.0-2_all.deb\n',
        'package-name 1.0.0-1 all none < 1.0.0-2 all none **CONFIGURE**\n',
        # Downgraded
        'package-name 1.0.0-2 all none > 1.0.0-1 all none /var/cache/apt/archives/package_name_.1.0.0-1_all.deb\n',
        'package-name 1.0.0-2 all none > 1.0.0-1 all none **CONFIGURE**\n',
        # Removed
        'package-name 1.0.0-1 all none > - - none **REMOVE**\n',
    ]
}
APT_LINES_TO_PARSE = [
    # (proto version, apt hook line index, expected group, expected package name, expected package version)
    # Installed
    (2, 0, 'installed', 'package-name', '1.0.0-1'),
    (2, 1, None, None, None),
    # Re-installed
    (2, 2, None, None, None),
    (2, 3, None, None, None),
    # Upgraded
    (2, 4, 'installed', 'package-name', '1.0.0-2'),
    (2, 5, None, None, None),
    # Downgraded
    (2, 6, 'installed', 'package-name', '1.0.0-1'),
    (2, 7, None, None, None),
    # Removed
    (2, 8, 'uninstalled', 'package-name', '1.0.0-1'),
    # Installed
    (3, 0, 'installed', 'package-name', '1.0.0-1'),
    (3, 1, None, None, None),
    # Re-installed
    (3, 2, None, None, None),
    (3, 3, None, None, None),
    # Upgraded
    (3, 4, 'installed', 'package-name', '1.0.0-2'),
    (3, 5, None, None, None),
    # Downgraded
    (3, 6, 'installed', 'package-name', '1.0.0-1'),
    (3, 7, None, None, None),
    # Removed
    (3, 8, 'uninstalled', 'package-name', '1.0.0-1'),
]
APT_PACKAGES = [
    AptPackage(name='package1', is_installed=True, installed=AptPkgVersion(source_name='package1', version='1.0.0-1'),
               candidate=None),
    AptPackage(name='package21', is_installed=True, installed=AptPkgVersion(source_name='package2', version='1.0.0-1'),
               candidate=None),
    AptPackage(name='package22', is_installed=True, installed=AptPkgVersion(source_name='package2', version='1.0.0-1'),
               candidate=None),
    AptPackage(name='package3', is_installed=True, installed=AptPkgVersion(source_name='package31', version='1.0.0-1'),
               candidate=None),
]
APT_UPGRADES = [
    AptPackage(name='package1', is_installed=True, installed=AptPkgVersion(source_name='package1', version='1.0.0-1'),
               candidate=AptPkgVersion(source_name='package1', version='1.0.0-2')),
    AptPackage(name='package3', is_installed=True, installed=AptPkgVersion(source_name='package31', version='1.0.0-1'),
               candidate=AptPkgVersion(source_name='package32', version='1.0.0-2')),
    AptPackage(name='package9', is_installed=False, installed=None, candidate=AptPkgVersion(
               source_name='package9', version='1.0.0-2')),
]
CLI_UPGRADES = [
    {'name': 'package1', 'version_from': '1.0.0-1', 'version_to': '1.0.0-2', 'source': 'package1'},
    {'name': 'package3', 'version_from': '1.0.0-1', 'version_to': '1.0.0-2', 'source': 'package32'},
]
CLI_PACKAGES = [
    {'name': 'package1', 'version': '1.0.0-1', 'source': 'package1'},
    {'name': 'package21', 'version': '1.0.0-1', 'source': 'package2'},
    {'name': 'package22', 'version': '1.0.0-1', 'source': 'package2'},
    {'name': 'package3', 'version': '1.0.0-1', 'source': 'package31'},
]


def test_parse_args_ok():
    """Calling parse_args with correct parameters should return the parsed arguments."""
    server = 'localhost'
    args = cli.parse_args(['-s', server])
    assert args.server == server


def test_parse_args_missing_server(capsys):
    """Calling parse_args without a -s/--server parameter should raise an error if -n/--dry-run is not set."""
    with pytest.raises(SystemExit):
        cli.parse_args([])
    _, err = capsys.readouterr()
    assert 'argument -s/--server is required unless -n/--dry-run is set' in err


def test_parse_args_missing_server_dry_run():
    """Calling parse_args without a -s/--server parameter should not raise an error if -n/--dry-run is set."""
    args = cli.parse_args(['-n'])
    assert args.dry_run


def test_parse_args_key_with_no_cert(capsys):
    """Calling parse_args with -k/--key but without -c/--cert should raise an error."""
    with pytest.raises(SystemExit):
        cli.parse_args(['-n', '-k', 'keypath'])
    _, err = capsys.readouterr()
    assert 'argument -c/--cert is required when -k/--key is set' in err


def test_parse_args_upgradable_dpkg(capsys):
    """Calling parse_args with both -u/--upgradable and -g/--dpkg should raise an error."""
    with pytest.raises(SystemExit):
        cli.parse_args(['-n', '-u', '-g'])
    _, err = capsys.readouterr()
    assert 'argument -u/--upgradable and -g/--dpkg-hook are mutually exclusive' in err


def test_parse_args_version(capsys):
    """Calling parse_args with --version should print the version and exit."""
    with pytest.raises(SystemExit):
        cli.parse_args(['--version'])
    out, _ = capsys.readouterr()
    assert 'debmonitor {ver}'.format(ver=cli.__version__) in out


def test_parse_apt_line_wrong_version():
    """Calling parse_apt_line with the wrong version should raise RuntimeError."""
    with pytest.raises(RuntimeError, match='Unsupported version'):
        cli.parse_apt_line('line', None, version=1)


@pytest.mark.parametrize('params', APT_LINES_TO_PARSE)
def test_parse_apt_lines(params):
    """Calling parse_apt_line with multiple lines and ensure that the result is the expected one."""
    group, package = cli.parse_apt_line(
        APT_HOOK_LINES[params[0]][params[1]], mocked_apt.cache.Cache(), version=params[0])
    assert group == params[2]
    if params[3] is None:
        assert package is None
    else:
        assert package['name'] == params[3]
        assert package['version'] == params[4]


def test_apt_filter_installed():
    """Calling AptInstalledFilter.apply() with an installed package should return True."""
    filter = cli.AptInstalledFilter()
    package = MagicMock()
    package.is_installed = True
    assert filter.apply(package)


def test_apt_filter_not_installed():
    """Calling AptInstalledFilter.apply() with a not installed package should return False."""
    filter = cli.AptInstalledFilter()
    package = MagicMock()
    package.is_installed = False
    assert filter.apply(package) is False


@pytest.mark.parametrize('upgradable_only', (False, True))
def test_get_packages_empty(upgradable_only):
    """Calling get_packages() with apt cache without pacakges should return a dictionary of empty lists."""
    packages = cli.get_packages(upgradable_only=upgradable_only)
    assert packages == {'installed': [], 'upgradable': [], 'uninstalled': []}


@pytest.mark.parametrize('upgradable_only', (False, True))
def test_get_packages(upgradable_only):
    """Calling get_packages() should return a dictionary of list of packages."""
    _reset_apt_caches()
    packages = cli.get_packages(upgradable_only=upgradable_only)
    if upgradable_only:
        assert packages == {'installed': [], 'upgradable': CLI_UPGRADES, 'uninstalled': []}
    else:
        assert packages == {'installed': CLI_PACKAGES, 'upgradable': CLI_UPGRADES, 'uninstalled': []}


def test_parse_dpkg_hook_no_version():
    """Calling parse_dpkg_hook() with a wrongly formatted version line should raise RuntimeError."""
    with pytest.raises(RuntimeError, match='Expected VERSION line to be the first one'):
        input_lines = [
            'VER 1\n',
            'APT::Architecture=amd64\n',
        ]
        cli.parse_dpkg_hook(input_lines)


def test_parse_dpkg_hook_wrong_version():
    """Calling parse_dpkg_hook() with an unsupported version line should raise RuntimeError."""
    input_lines = [
        'VERSION 4\n',
        'APT::Architecture=amd64\n',
    ]
    with pytest.raises(RuntimeError, match='Unsupported version'):
        cli.parse_dpkg_hook(input_lines)


def test_parse_dpkg_hook_no_separator():
    """Calling parse_dpkg_hook() with no empty separator should raise a RuntimeError."""
    input_lines = [
        'VERSION 3\n',
        'APT::Architecture=amd64\n',
    ]
    with pytest.raises(RuntimeError, match='Unable to find the empty line separator in input'):
        cli.parse_dpkg_hook(input_lines)


def test_parse_dpkg_hook_no_packages():
    """Calling parse_dpkg_hook() with no update lines should return an empty dictionary."""
    input_lines = [
        'VERSION 3\n',
        'APT::Architecture=amd64\n',
        '\n',
    ]
    assert cli.parse_dpkg_hook(input_lines) == {}


@pytest.mark.parametrize('version', (2, 3))
@pytest.mark.parametrize('apt_line', (
    # APT_HOOK_LINES start index, APT_HOOK_LINES end index, apt cache package
    (0, 2, AptPackage(name='package-name', is_installed=False, installed=None,
                      candidate=AptPkgVersion(source_name='package-name', version='1.0.0-1'))),
    (2, 4, AptPackage(name='package-name', is_installed=True,
                      installed=AptPkgVersion(source_name='package-name', version='1.0.0-1'), candidate=None)),
    (4, 6, AptPackage(name='package-name', is_installed=True,
                      installed=AptPkgVersion(source_name='package-name', version='1.0.0-1'),
                      candidate=AptPkgVersion(source_name='package-name', version='1.0.0-2'))),
    (6, 8, AptPackage(name='package-name', is_installed=True,
                      installed=AptPkgVersion(source_name='package-name', version='1.0.0-2'),
                      candidate=AptPkgVersion(source_name='package-name', version='1.0.0-1'))),
    (8, 9, AptPackage(name='package-name', is_installed=True,
                      installed=AptPkgVersion(source_name='package-name', version='1.0.0-1'), candidate=None)),
))
def test_parse_dpkg_hook(version, apt_line):
    """Calling parse_dpkg_hook() should parse the list of packages reported by a Dpkg::Pre-Install-Pkgs hook."""
    mocked_apt.cache.Cache().__getitem__.return_value = apt_line[2]
    input_lines = _get_dpkg_hook_preamble(version) + APT_HOOK_LINES[version][apt_line[0]:apt_line[1]]

    packages = cli.parse_dpkg_hook(input_lines)

    expected_packages = {'installed': [], 'upgradable': [], 'uninstalled': []}
    package = {'name': 'package-name', 'version': '', 'source': 'package-name'}
    if apt_line[0] == 2:
        pass  # Re-installed package, no changes
    elif apt_line[0] == 8:
        package['version'] = apt_line[2].installed.version
        expected_packages['uninstalled'].append(package)
    else:
        package['version'] = apt_line[2].candidate.version
        expected_packages['installed'].append(package)

    assert packages == expected_packages


def test_self_update_head_fail(mocked_requests):
    """Calling self_update() when the HEAD request to DebMonitor fail should raise RuntimeError."""
    mocked_requests.register_uri('HEAD', DEBMONITOR_CLIENT_URL, status_code=500)
    with pytest.raises(RuntimeError, match='Unable to check remote script version'):
        cli.self_update(DEBMONITOR_BASE_URL, None)

    assert mocked_requests.called


def test_self_update_head_no_header(mocked_requests):
    """Calling self_update() when the HEAD request is missing the expected header should raise RuntimeError."""
    mocked_requests.register_uri('HEAD', DEBMONITOR_CLIENT_URL, status_code=200)
    with pytest.raises(RuntimeError, match='No header {header} value found'.format(header=cli.CLIENT_VERSION_HEADER)):
        cli.self_update(DEBMONITOR_BASE_URL, None)

    assert mocked_requests.called


def test_self_update_head_same_version(mocked_requests):
    """Calling self_update() when client on DebMonitor is at the same version should return without doing anything."""
    mocked_requests.register_uri(
        'HEAD', DEBMONITOR_CLIENT_URL, status_code=200, headers={cli.CLIENT_VERSION_HEADER: cli.__version__})

    ret = cli.self_update(DEBMONITOR_BASE_URL, None)

    assert ret is None
    assert mocked_requests.called


def test_self_update_has_update_fail(mocked_requests):
    """Calling self_update() when the GET request to DebMonitor fail should raise RuntimeError."""
    mocked_requests.register_uri(
        'HEAD', DEBMONITOR_CLIENT_URL, status_code=200, headers={cli.CLIENT_VERSION_HEADER: DEBMONITOR_CLIENT_VERSION})
    mocked_requests.register_uri('GET', DEBMONITOR_CLIENT_URL, status_code=500)

    with pytest.raises(RuntimeError, match='Unable to download remote script'):
        cli.self_update(DEBMONITOR_BASE_URL, None)

    assert mocked_requests.called


def test_self_update_has_update_wrong_hash(mocked_requests):
    """Calling self_update() when the checksum mismatch should raise RuntimeError."""
    mocked_requests.register_uri(
        'HEAD', DEBMONITOR_CLIENT_URL, status_code=200, headers={cli.CLIENT_VERSION_HEADER: DEBMONITOR_CLIENT_VERSION})
    mocked_requests.register_uri('GET', DEBMONITOR_CLIENT_URL, status_code=200, text='data',
                                 headers={cli.CLIENT_VERSION_HEADER: DEBMONITOR_CLIENT_VERSION,
                                          cli.CLIENT_CHECKSUM_HEADER: '000000'})

    with pytest.raises(RuntimeError, match='The checksum of the script do not match the HTTP header'):
        cli.self_update(DEBMONITOR_BASE_URL, None)

    assert mocked_requests.called


def test_self_update_has_update_ok(mocked_requests):
    """Calling self_update() should self-update the CLI script."""
    mocked_requests.register_uri(
        'HEAD', DEBMONITOR_CLIENT_URL, status_code=200, headers={cli.CLIENT_VERSION_HEADER: DEBMONITOR_CLIENT_VERSION})
    mocked_requests.register_uri(
        'GET', DEBMONITOR_CLIENT_URL, status_code=200, text='data', headers={
            cli.CLIENT_VERSION_HEADER: DEBMONITOR_CLIENT_VERSION,
            cli.CLIENT_CHECKSUM_HEADER: DEBMONITOR_CLIENT_CHECKSUM})

    with patch('builtins.open', mock_open()) as mocked_open:
        cli.self_update(DEBMONITOR_BASE_URL, None)

        mocked_open.assert_called_once_with(os.path.realpath(cli.__file__), mode='w')
        mocked_handler = mocked_open()
        mocked_handler.write.assert_called_once_with('data')

    assert mocked_requests.called


@pytest.mark.parametrize('params', ([], ['-u'], ['-k', 'cert.key', '-c', 'cert.pem'], ['-c', 'cert.pem']))
@patch('socket.getfqdn', return_value=HOSTNAME)
def test_main(mocked_getfqdn, params, mocked_requests):
    """Calling main() should send the updates to the DebMonitor server with the above parameters."""
    args = cli.parse_args(['-s', DEBMONITOR_SERVER] + params)
    mocked_requests.register_uri('POST', DEBMONITOR_UPDATE_URL, status_code=201)
    _reset_apt_caches()

    exit_code = cli.main(args)

    mocked_getfqdn.assert_called_once_with()
    assert mocked_requests.called
    assert exit_code == 0
    assert mocked_requests.last_request.json() == _get_payload_with_packages(params)


@patch('socket.getfqdn', return_value=HOSTNAME)
def test_main_no_packages(mocked_getfqdn):
    """Calling main() if there are no updates should success without sending any update to the DebMonitor server."""
    args = cli.parse_args(['-s', DEBMONITOR_SERVER])
    _reset_apt_caches(empty=True)

    exit_code = cli.main(args)

    mocked_getfqdn.assert_called_once_with()
    assert exit_code == 0


@patch('socket.getfqdn', return_value=HOSTNAME)
def test_main_dry_run(mocked_getfqdn, capsys):
    """Calling main() with dry-run parameter should print the updates without sending them to the DebMonitor server."""
    args = cli.parse_args(['-s', DEBMONITOR_SERVER, '-n'])
    _reset_apt_caches()

    exit_code = cli.main(args)

    out, _ = capsys.readouterr()
    mocked_getfqdn.assert_called_once_with()
    assert exit_code == 0
    assert json.loads(out) == _get_payload_with_packages([])


@pytest.mark.parametrize('params', ([], ['-d']))
@patch('socket.getfqdn', return_value=HOSTNAME)
def test_main_wrong_http_code(mocked_getfqdn, params, mocked_requests, caplog):
    """Calling main() when the DebMonitor server returns a wrong HTTP code should return 1."""
    args = cli.parse_args(['-s', DEBMONITOR_SERVER] + params)
    mocked_requests.register_uri('POST', DEBMONITOR_UPDATE_URL, status_code=400)
    _reset_apt_caches()

    exit_code = cli.main(args)

    mocked_getfqdn.assert_called_once_with()
    assert mocked_requests.called
    assert exit_code == 1
    assert mocked_requests.last_request.json() == _get_payload_with_packages(params)
    assert 'Failed to send the update to the DebMonitor server' in caplog.text


@patch('socket.getfqdn', return_value=HOSTNAME)
def test_main_dpkg_hook(mocked_getfqdn, mocked_requests):
    """Calling main() with -g should parse the input for a Dpkg::Pre-Install-Pkgs hook and send the update."""
    args = cli.parse_args(['-s', DEBMONITOR_SERVER, '-g'])
    input_lines = _get_dpkg_hook_preamble(3) + APT_HOOK_LINES[3][0:2]
    mocked_requests.register_uri('POST', DEBMONITOR_UPDATE_URL, status_code=201)
    mocked_apt.cache.Cache().__getitem__.return_value = AptPackage(
        name='package-name', is_installed=False, installed=None,
        candidate=AptPkgVersion(source_name='package-name', version='1.0.0-1'))

    exit_code = cli.main(args, input_lines=input_lines)

    mocked_getfqdn.assert_called_once_with()
    assert mocked_requests.called
    assert exit_code == 0
    assert mocked_requests.last_request.json() == _get_payload_with_packages(['-g'])


@patch('socket.getfqdn', return_value=HOSTNAME)
def test_main_update_fail(mocked_getfqdn, mocked_requests, caplog):
    """Calling main() whit --update that fails the update should log the error and continue."""
    args = cli.parse_args(['-s', DEBMONITOR_SERVER, '--update'])
    mocked_requests.register_uri('POST', DEBMONITOR_UPDATE_URL, status_code=201)
    mocked_requests.register_uri('HEAD', DEBMONITOR_CLIENT_URL, status_code=500)
    _reset_apt_caches()

    exit_code = cli.main(args)

    assert mocked_requests.called
    mocked_getfqdn.assert_called_once_with()
    assert exit_code == 0
    assert 'Unable to self-update this script' in caplog.text


@patch('socket.getfqdn', return_value=HOSTNAME)
def test_main_update_ok(mocked_getfqdn, mocked_requests, caplog):
    """Calling main() whit --update that succeed should update the CLI script."""
    args = cli.parse_args(['-s', DEBMONITOR_SERVER, '--update'])
    mocked_requests.register_uri('POST', DEBMONITOR_UPDATE_URL, status_code=201)
    mocked_requests.register_uri(
        'HEAD', DEBMONITOR_CLIENT_URL, status_code=200, headers={cli.CLIENT_VERSION_HEADER: DEBMONITOR_CLIENT_VERSION})
    mocked_requests.register_uri(
        'GET', DEBMONITOR_CLIENT_URL, status_code=200, text='data', headers={
            cli.CLIENT_VERSION_HEADER: DEBMONITOR_CLIENT_VERSION,
            cli.CLIENT_CHECKSUM_HEADER: DEBMONITOR_CLIENT_CHECKSUM})
    _reset_apt_caches()

    with patch('builtins.open', mock_open()) as mocked_open:
        exit_code = cli.main(args)

        mocked_open.assert_called_once_with(os.path.realpath(cli.__file__), mode='w')
        mocked_handler = mocked_open()
        mocked_handler.write.assert_called_once_with('data')

    assert mocked_requests.called
    mocked_getfqdn.assert_called_once_with()
    assert exit_code == 0
    assert 'Successfully self-updated DebMonitor CLI' in caplog.text


def _get_payload_with_packages(params):
    """Given the current CLI parameters return the expected payload to be sent by DebMonitor."""
    if params == ['-u']:
        installed = []
        upgradable = CLI_UPGRADES
        upgrade_type = 'partial'
    elif params == ['-g']:
        installed = [{'name': 'package-name', 'version': '1.0.0-1', 'source': 'package-name'}]
        upgradable = []
        upgrade_type = 'partial'
    else:
        installed = CLI_PACKAGES
        upgradable = CLI_UPGRADES
        upgrade_type = 'full'

    payload = {
        'api_version': 'v1',
        'os': OS_NAME,
        'hostname': HOSTNAME,
        'running_kernel': {
            'release': KERNEL_RELEASE,
            'version': KERNEL_VERSION,
        },
        'installed': installed,
        'uninstalled': [],
        'upgradable': upgradable,
        'update_type': upgrade_type,
    }

    return payload


def _reset_apt_caches(empty=False):
    """Reset the mocked apt caches with the pre-defined packages or none if empty is True."""
    if empty:
        installed = []
        upgrades = []
    else:
        installed = APT_PACKAGES
        upgrades = APT_UPGRADES

    mocked_apt.cache.FilteredCache().__iter__.return_value = installed
    mocked_apt.cache.FilteredCache().__len__.return_value = len(installed)
    mocked_apt.cache.FilteredCache().get_changes.return_value = upgrades


def _get_dpkg_hook_preamble(version):
    return [
        'VERSION {version}\n'.format(version=version),
        'APT::Architecture=amd64\n',
        'APT::Build-Essential::=build-essential\n',
        'APT::Install-Recommends=0\n',
        'APT::Install-Suggests=0\n',
        '\n',
    ]
