from datetime import UTC, datetime
from pathlib import Path

import pytest

from debscp.backends.base import RemoteBackend
from debscp.models import RemoteEntry
from debscp.sync import SyncAction, SyncDirection, SyncEngine, SyncOperation


class FakeBackend(RemoteBackend):
    def __init__(self, entries):
        self.entries = entries

    def connect(self):
        pass

    def close(self):
        pass

    def listdir(self, path):
        return self.entries.get(path, [])

    def download(self, remote, local, progress=None):
        local.write_text("remote")

    def upload(self, local, remote, progress=None):
        pass

    def mkdir(self, path):
        pass

    def remove(self, path, *, directory=False):
        pass

    def rename(self, source, destination):
        pass


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


def test_deletions_are_ordered_children_before_parents(tmp_path: Path) -> None:
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "file.txt").write_text("data")
    engine = SyncEngine(FakeBackend({"/": []}))
    actions = engine.compare(tmp_path, "/", SyncDirection.DOWNLOAD, delete=True)
    assert [item.relative_path for item in actions] == ["folder/file.txt", "folder"]
    engine.apply(actions, tmp_path, "/")
    assert not folder.exists()


def test_type_mismatch_is_an_explicit_blocking_conflict(tmp_path: Path) -> None:
    (tmp_path / "same").write_text("local file")
    remote = RemoteEntry("same", "/same", 0, datetime.now(UTC), 0, True)
    engine = SyncEngine(FakeBackend({"/": [remote], "/same": []}))
    actions = engine.compare(tmp_path, "/")
    assert actions == [SyncAction(SyncOperation.CONFLICT, "same", "file/directory type mismatch")]
    with pytest.raises(ValueError, match="file/directory conflicts"):
        engine.apply(actions, tmp_path, "/")


def test_keep_up_to_date_does_not_repeat_unchanged_upload(tmp_path: Path, monkeypatch) -> None:
    local = tmp_path / "same.txt"
    local.write_text("same")
    remote = RemoteEntry("same.txt", "/same.txt", 4, datetime.fromtimestamp(0, UTC), 0, False)
    backend = FakeBackend({"/": [remote]})
    uploads: list[str] = []
    backend.upload = lambda _local, path, progress=None: uploads.append(path)
    monkeypatch.setattr("debscp.sync.time.sleep", lambda _seconds: None)
    SyncEngine(backend).keep_up_to_date(tmp_path, "/", interval=0, stop_after=3)
    assert uploads == ["/same.txt"]
