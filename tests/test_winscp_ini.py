from __future__ import annotations

from debscp.winscp_ini import load_winscp_ini


def test_imports_supported_winscp_protocols_and_advanced_fields(tmp_path) -> None:
    backup = tmp_path / "WinSCP.ini"
    backup.write_text(
        """
[Configuration\\Interface]
RandomSeedFile=%25APPDATA%25%5Cseed.rnd

[Sessions\\Default%20Settings]
FSProtocol=1

[Sessions\\SSH%20Lab]
HostName=alice%40sftp.example.test
PortNumber=2222
FSProtocol=2
PublicKeyFile=C%3A%5CKeys%5Cid_ed25519
RemoteDirectory=%2Fupload%20area
Tunnel=1
TunnelHostName=bastion.example.test
TunnelUserName=jumper
TunnelPortNumber=2200
Password=ABC123

[Sessions\\Legacy SCP]
HostName=scp.example.test
UserName=bob
FSProtocol=0

[Sessions\\Secure FTP]
HostName=ftp.example.test
UserName=ftp-user
FSProtocol=5
Ftps=3
PortNumber=21

[Sessions\\DAV]
HostName=dav.example.test
UserName=dav-user
FSProtocol=6
Ftps=1
PortNumber=443
RemoteDirectory=%2Fdocuments

[Sessions\\Object Store]
HostName=s3.eu.example.test
UserName=ACCESS_KEY
FSProtocol=7
Ftps=1
PortNumber=443
RemoteDirectory=%2Fmy-bucket%2Freports
S3DefaultRegion=eu-west-2
""".strip(),
        encoding="utf-8-sig",
    )

    result = load_winscp_ini(backup)

    assert [item.name for item in result.sessions] == ["SSH Lab", "Legacy SCP", "Secure FTP", "DAV", "Object Store"]
    ssh = result.sessions[0]
    assert (ssh.protocol, ssh.username, ssh.host, ssh.port) == ("sftp", "alice", "sftp.example.test", 2222)
    assert ssh.key_file == r"C:\Keys\id_ed25519"
    assert ssh.remote_path == "/upload area"
    assert ssh.jump_host == "-p 2200 jumper@bastion.example.test"
    assert result.sessions[1].protocol == "scp"
    assert (result.sessions[2].protocol, result.sessions[2].tls) == ("ftps", True)
    assert (result.sessions[3].protocol, result.sessions[3].remote_path) == ("webdavs", "/documents")
    s3 = result.sessions[4]
    assert (s3.host, s3.remote_path, s3.endpoint_url, s3.region) == (
        "my-bucket",
        "/reports",
        "https://s3.eu.example.test",
        "eu-west-2",
    )
    assert any("password was not imported" in warning for warning in result.warnings)


def test_skips_non_sites_workspaces_and_unsupported_protocols(tmp_path) -> None:
    backup = tmp_path / "backup.ini"
    backup.write_text(
        """
[Sessions\\No Host]
UserName=user
[Sessions\\Workspace]
HostName=host
IsWorkspace=1
[Sessions\\Unsupported]
HostName=host
FSProtocol=99
""".strip()
    )
    result = load_winscp_ini(backup)
    assert result.sessions == ()
    assert len(result.warnings) == 3


def test_supports_utf16_backup_and_invalid_port_fallback(tmp_path) -> None:
    backup = tmp_path / "backup.ini"
    backup.write_text(
        "[Sessions\\München]\nHostName=host.example\nPortNumber=70000\n",
        encoding="utf-16",
    )
    result = load_winscp_ini(backup)
    assert result.sessions[0].name == "München"
    assert result.sessions[0].port == 22
    assert "invalid PortNumber" in result.warnings[0]


def test_applies_default_settings_and_decodes_winscp_unicode_marker(tmp_path) -> None:
    backup = tmp_path / "backup.ini"
    backup.write_text(
        """
[Sessions\\Default%20Settings]
UserName=default-user
RemoteDirectory=%2Fshared
[Sessions\\%EF%BB%BFM%C3%BCnchen]
HostName=host.example
""".strip()
    )
    result = load_winscp_ini(backup)
    assert result.sessions[0].name == "München"
    assert result.sessions[0].username == "default-user"
    assert result.sessions[0].remote_path == "/shared"


def test_preserves_implicit_ftps_mode(tmp_path) -> None:
    backup = tmp_path / "backup.ini"
    backup.write_text(
        "[Sessions\\Implicit FTPS]\nHostName=ftp.example\nUserName=user\nFSProtocol=5\nFtps=1\nPortNumber=990\n"
    )
    session = load_winscp_ini(backup).sessions[0]
    assert (session.protocol, session.port, session.tls) == ("ftps-implicit", 990, True)


def test_reports_windows_local_directories_without_exposing_paths(tmp_path) -> None:
    backup = tmp_path / "backup.ini"
    backup.write_text(
        "[Sessions\\Site]\nHostName=host.example\nUserName=user\nLocalDirectory=C%3A%5CUsers%5CAlice%5CFiles\n"
    )
    result = load_winscp_ini(backup)
    assert result.sessions[0].host == "host.example"
    assert result.warnings == (
        "1 site(s): Windows LocalDirectory values were not imported because they are not valid Linux paths",
    )
    assert "Alice" not in result.warnings[0]


def test_decrypts_standard_winscp_password_without_exposing_it_in_repr(tmp_path) -> None:
    def encode(value: int) -> str:
        return f"{(((~value) & 0xFF) ^ 0xA3):02X}"

    username, host, password = "alice", "host.example", "correct horse"
    payload = (username + host + password).encode()
    encrypted = "".join([encode(0xFF), encode(0), encode(len(payload)), encode(0), *(encode(item) for item in payload)])
    backup = tmp_path / "backup.ini"
    backup.write_text(f"[Sessions\\Site]\nHostName={host}\nUserName={username}\nPassword={encrypted}\n")
    result = load_winscp_ini(backup)
    assert result.credentials[0].session_name == "Site"
    assert result.credentials[0].password == password
    assert password not in repr(result)
