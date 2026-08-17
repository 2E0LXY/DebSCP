from datetime import UTC, datetime

from debscp.models import RemoteEntry, normalize_remote_path


def test_normalize_remote_path() -> None:
    assert normalize_remote_path("/srv/../home/./user") == "/home/user"
    assert normalize_remote_path("../../etc") == "/etc"


def test_display_size() -> None:
    entry = RemoteEntry("x", "/x", 1536, datetime.fromtimestamp(0, UTC), 0, False)
    assert entry.display_size == "1.5 KiB"
