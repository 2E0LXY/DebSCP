from datetime import UTC, datetime

from debscp.gui import DebSCPWindow, display_size, local_type
from debscp.models import RemoteEntry, SessionConfig


class Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def test_config_save_preserves_advanced_profile_fields() -> None:
    original = SessionConfig(
        "advanced",
        "bucket",
        "key",
        port=443,
        protocol="s3",
        endpoint_url="https://objects.example",
        region="eu-west-2",
        proxy_command="proxy command",
        jump_host="jump.example",
    )
    window = object.__new__(DebSCPWindow)
    window.sessions = [original]
    window.session_name = Variable("advanced")
    window.host = Variable("new-bucket")
    window.username = Variable("new-key")
    window.port = Variable("443")
    window.key_file = Variable("")
    window.remote_path_var = Variable("/prefix")
    window.protocol_name = Variable("s3")
    saved = window._config()
    assert (saved.endpoint_url, saved.region, saved.proxy_command, saved.jump_host) == (
        original.endpoint_url,
        original.region,
        original.proxy_command,
        original.jump_host,
    )


class RecordingBackend:
    def __init__(self):
        self.removed = []

    def remove(self, path, *, directory=False):
        self.removed.append((path, directory))

    def remove_tree(self, path):
        self.removed.append((path, True))


def test_queued_remote_delete_captures_originating_backend(monkeypatch) -> None:
    first, second = RecordingBackend(), RecordingBackend()
    entry = RemoteEntry("victim", "/victim", 1, datetime.now(UTC), 0, False)
    window = object.__new__(DebSCPWindow)
    window.backend = first
    window._selected_remote = lambda: entry
    pending = []
    window._background = pending.append
    window.after = lambda _delay, callback, *args: callback(*args)
    window._refresh_backend = lambda _backend: None
    monkeypatch.setattr("debscp.gui.messagebox.askyesno", lambda *args, **kwargs: True)
    window._remote_delete()
    window.backend = second
    pending[0]()
    assert first.removed == [("/victim", False)]
    assert second.removed == []


def test_file_pane_display_helpers(tmp_path) -> None:
    folder = tmp_path / "Projects"
    folder.mkdir()
    document = tmp_path / "release.tar.gz"
    document.write_bytes(b"x" * 1536)
    assert local_type(folder) == "File folder"
    assert local_type(document) == "GZ file"
    assert display_size(document.stat().st_size) == "1.5 KiB"
