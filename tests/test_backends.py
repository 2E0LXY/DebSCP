from datetime import UTC, datetime

import pytest

from debscp.backends import FTPBackend, S3Backend, SCPBackend, SFTPBackend, WebDAVBackend, create_backend
from debscp.backends.base import RemoteBackend
from debscp.models import RemoteEntry, SessionConfig


def test_backend_factory_selects_every_protocol() -> None:
    expected = {
        "sftp": SFTPBackend,
        "scp": SCPBackend,
        "ftp": FTPBackend,
        "ftps": FTPBackend,
        "ftps-implicit": FTPBackend,
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


def test_capabilities_distinguish_download_and_upload_resume() -> None:
    assert SFTPBackend.capabilities.download_resume
    assert not SFTPBackend.capabilities.upload_resume
    assert S3Backend.capabilities.download_resume
    assert not S3Backend.capabilities.upload_resume


class FailingTreeBackend(RemoteBackend):
    def connect(self):
        pass

    def close(self):
        pass

    def listdir(self, path):
        return []

    def download(self, remote, local, progress=None):
        pass

    def upload(self, local, remote, progress=None):
        pass

    def mkdir(self, path):
        raise PermissionError("denied")

    def remove(self, path, *, directory=False):
        pass

    def rename(self, source, destination):
        pass


def test_recursive_upload_does_not_hide_mkdir_failures(tmp_path) -> None:
    with pytest.raises(PermissionError, match="denied"):
        FailingTreeBackend().upload_tree(tmp_path, "/target")


class RecordingTreeBackend(FailingTreeBackend):
    def __init__(self):
        self.entries = {
            "/folder": [RemoteEntry("child", "/folder/child", 1, datetime.now(UTC), 0, False)],
        }
        self.removed = []

    def listdir(self, path):
        return self.entries.get(path, [])

    def remove(self, path, *, directory=False):
        self.removed.append((path, directory))


def test_recursive_remove_deletes_children_before_directory() -> None:
    backend = RecordingTreeBackend()
    backend.remove_tree("/folder")
    assert backend.removed == [("/folder/child", False), ("/folder", True)]
