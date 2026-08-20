from datetime import UTC, datetime

import pytest

from debscp.editor import RemoteEditor
from debscp.models import RemoteEntry
from tests.test_sync import FakeBackend


def test_editor_requires_explicit_wait_capable_command(tmp_path, monkeypatch) -> None:
    entry = RemoteEntry("remote.txt", "/remote.txt", 4, datetime.now(UTC), 0, False)
    backend = FakeBackend({"/": [entry]})
    backend.download = lambda _remote, local, progress=None: local.write_text("data")
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    with pytest.raises(ValueError, match="Set VISUAL or EDITOR"):
        RemoteEditor(backend).edit("/remote.txt")
