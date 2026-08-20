import json

from debscp.resume import finish_partial, metadata_path, prepare_partial


def test_stale_or_unidentified_partial_is_discarded(tmp_path) -> None:
    partial = tmp_path / "file.debscp-part"
    partial.write_bytes(b"wrong-prefix")
    metadata_path(partial).write_text(json.dumps({"etag": "old"}))
    assert prepare_partial(partial, {"etag": "new"}, 20) == 0
    assert not partial.exists()

    partial.write_bytes(b"unverified")
    assert prepare_partial(partial, None, 20) == 0
    assert not partial.exists()


def test_verified_partial_resumes_and_metadata_is_cleaned(tmp_path) -> None:
    partial = tmp_path / "file.debscp-part"
    destination = tmp_path / "file"
    identity = {"etag": "same", "size": 7}
    partial.write_bytes(b"partial")
    metadata_path(partial).write_text(json.dumps(identity, sort_keys=True))
    assert prepare_partial(partial, identity, 10) == 7
    partial.write_bytes(b"completed")
    finish_partial(partial, destination)
    assert destination.read_bytes() == b"completed"
    assert not metadata_path(partial).exists()
