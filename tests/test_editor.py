from datetime import UTC, datetime

import pytest

from debscp.backends.base import RemoteBackend
from debscp.editor import RemoteEditor
from debscp.models import RemoteEntry


class EditorBackend(RemoteBackend):
    def __init__(self, entry):
        self.entry = entry

    def connect(self):
        pass

    def close(self):
        pass

    def listdir(self, path):
        return [self.entry]

    def download(self, remote, local, progress=None):
        local.write_text("data")

    def upload(self, local, remote, progress=None):
        pass

    def mkdir(self, path):
        pass

    def remove(self, path, *, directory=False):
        pass

    def rename(self, source, destination):
        pass


def test_editor_requires_explicit_wait_capable_command(tmp_path, monkeypatch) -> None:
    entry = RemoteEntry("remote.txt", "/remote.txt", 4, datetime.now(UTC), 0, False)
    backend = EditorBackend(entry)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    with pytest.raises(ValueError, match="Set VISUAL or EDITOR"):
        RemoteEditor(backend).edit("/remote.txt")
