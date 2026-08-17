from datetime import UTC, datetime
from pathlib import Path

from debscp.backends.base import RemoteBackend
from debscp.models import RemoteEntry
from debscp.sync import SyncDirection, SyncEngine, SyncOperation


class FakeBackend(RemoteBackend):
    def __init__(self, entries):
        self.entries = entries

    def connect(self): pass
    def close(self): pass
    def listdir(self, path): return self.entries.get(path, [])
    def download(self, remote, local, progress=None): local.write_text("remote")
    def upload(self, local, remote, progress=None): pass
    def mkdir(self, path): pass
    def remove(self, path, *, directory=False): pass
    def rename(self, source, destination): pass


def test_sync_builds_reviewable_checklist(tmp_path: Path) -> None:
    (tmp_path / "local.txt").write_text("local")
    remote = RemoteEntry("remote.txt", "/remote.txt", 6, datetime.now(UTC), 0, False)
    actions = SyncEngine(FakeBackend({"/": [remote]})).compare(tmp_path, "/", SyncDirection.BOTH)
    assert {(item.operation, item.relative_path) for item in actions} == {
        (SyncOperation.UPLOAD, "local.txt"),
        (SyncOperation.DOWNLOAD, "remote.txt"),
    }


def test_upload_direction_can_delete_remote_extras(tmp_path: Path) -> None:
    remote = RemoteEntry("old.txt", "/old.txt", 1, datetime.now(UTC), 0, False)
    actions = SyncEngine(FakeBackend({"/": [remote]})).compare(tmp_path, "/", SyncDirection.UPLOAD, delete=True)
    assert actions[0].operation == SyncOperation.DELETE_REMOTE

