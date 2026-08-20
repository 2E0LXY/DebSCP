from __future__ import annotations

import json
from pathlib import Path


def metadata_path(temporary: Path) -> Path:
    return temporary.with_name(temporary.name + ".json")


def prepare_partial(temporary: Path, identity: dict[str, object] | None, total: int) -> int:
    """Return a safe offset, discarding partial data that cannot be tied to its source."""
    metadata = metadata_path(temporary)
    saved: object = None
    if metadata.exists():
        try:
            saved = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            saved = None
    if identity is None or saved != identity:
        temporary.unlink(missing_ok=True)
        metadata.unlink(missing_ok=True)
    if identity is None:
        return 0
    offset = temporary.stat().st_size if temporary.exists() else 0
    if offset > total:
        temporary.unlink(missing_ok=True)
        offset = 0
    metadata.write_text(json.dumps(identity, sort_keys=True), encoding="utf-8")
    return offset


def finish_partial(temporary: Path, destination: Path) -> None:
    temporary.replace(destination)
    metadata_path(temporary).unlink(missing_ok=True)
