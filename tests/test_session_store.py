import json
import os
import stat

from debscp.models import SessionConfig
from debscp.session_store import SessionStore


def test_store_round_trip(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions.json")
    session = SessionConfig("lab", "host.example", "alex", key_file="~/.ssh/id_ed25519")
    store.upsert(session)
    assert store.load() == [session]
    if os.name != "nt":
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert "password" not in json.dumps(json.loads(store.path.read_text()))


def test_upsert_replaces_by_name(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions.json")
    store.upsert(SessionConfig("lab", "old", "alex"))
    store.upsert(SessionConfig("lab", "new", "alex"))
    assert [item.host for item in store.load()] == ["new"]


def test_folder_round_trip_and_profile_rename(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions.json")
    original = SessionConfig("Primary", "old.example", "alex", folder="Work")
    store.upsert(original)

    renamed = SessionConfig("Production", "new.example", "alex", folder="Servers")
    store.replace("Primary", renamed)

    assert store.load() == [renamed]


def test_merge_renames_collisions_or_overwrites(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions.json")
    store.upsert(SessionConfig("lab", "old", "alex"))
    stored, renamed = store.merge([SessionConfig("lab", "imported", "alex")])
    assert stored == ["lab 2"]
    assert renamed == ["lab → lab 2"]
    assert [item.name for item in store.load()] == ["lab", "lab 2"]

    stored, renamed = store.merge([SessionConfig("lab", "replacement", "alex")], overwrite=True)
    assert (stored, renamed) == (["lab"], [])
    assert next(item for item in store.load() if item.name == "lab").host == "replacement"
