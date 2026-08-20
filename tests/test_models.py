from datetime import UTC, datetime

import pytest

from debscp.models import RemoteEntry, default_port, normalize_remote_path


def test_normalize_remote_path() -> None:
    assert normalize_remote_path("/srv/../home/./user") == "/home/user"
    assert normalize_remote_path("../../etc") == "/etc"


def test_display_size() -> None:
    entry = RemoteEntry("x", "/x", 1536, datetime.fromtimestamp(0, UTC), 0, False)
    assert entry.display_size == "1.5 KiB"


def test_protocol_default_ports() -> None:
    assert {name: default_port(name) for name in ("sftp", "scp", "ftp", "ftps", "webdav", "webdavs", "s3")} == {
        "sftp": 22,
        "scp": 22,
        "ftp": 21,
        "ftps": 21,
        "webdav": 80,
        "webdavs": 443,
        "s3": 443,
    }
    with pytest.raises(ValueError, match="Unsupported protocol"):
        default_port("gopher")
