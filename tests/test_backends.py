from debscp.backends import FTPBackend, S3Backend, SCPBackend, SFTPBackend, WebDAVBackend, create_backend
from debscp.models import SessionConfig


def test_backend_factory_selects_every_protocol() -> None:
    expected = {
        "sftp": SFTPBackend,
        "scp": SCPBackend,
        "ftp": FTPBackend,
        "ftps": FTPBackend,
        "webdav": WebDAVBackend,
        "webdavs": WebDAVBackend,
        "s3": S3Backend,
    }
    for protocol, implementation in expected.items():
        config = SessionConfig("test", "example.test", "user", protocol=protocol)
        assert isinstance(create_backend(config), implementation)


def test_legacy_session_defaults_to_sftp() -> None:
    config = SessionConfig.from_dict({"name": "old", "host": "example.test", "username": "user"})
    assert config.protocol == "sftp"
    assert config.port == 22

