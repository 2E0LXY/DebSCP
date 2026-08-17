from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import PurePosixPath


@dataclass(slots=True)
class SessionConfig:
    name: str
    host: str
    username: str
    port: int = 22
    key_file: str | None = None
    remote_path: str = "/"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> SessionConfig:
        return cls(
            name=str(value["name"]),
            host=str(value["host"]),
            username=str(value["username"]),
            port=int(value.get("port", 22)),
            key_file=str(value["key_file"]) if value.get("key_file") else None,
            remote_path=str(value.get("remote_path", "/")),
        )


@dataclass(frozen=True, slots=True)
class RemoteEntry:
    name: str
    path: str
    size: int
    modified: datetime
    mode: int
    is_dir: bool
    is_link: bool = False

    @property
    def display_size(self) -> str:
        if self.is_dir:
            return "—"
        value = float(self.size)
        for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
            if value < 1024 or unit == "TiB":
                return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} TiB"


def normalize_remote_path(path: str) -> str:
    """Return a normalized absolute POSIX path without allowing traversal."""
    candidate = PurePosixPath("/", path)
    parts: list[str] = []
    for part in candidate.parts:
        if part in ("", "/", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
        else:
            parts.append(part)
    return "/" + "/".join(parts)
