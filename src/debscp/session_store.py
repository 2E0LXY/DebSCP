from __future__ import annotations

import json
import os
from pathlib import Path

from .models import SessionConfig


class SessionStore:
    """Stores non-secret connection profiles with owner-only permissions."""

    def __init__(self, path: Path | None = None) -> None:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self.path = path or config_home / "debscp" / "sessions.json"

    def load(self) -> list[SessionConfig]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise TypeError("sessions.json must contain a list")
        return [SessionConfig.from_dict(item) for item in raw]

    def save(self, sessions: list[SessionConfig]) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps([session.to_dict() for session in sessions], indent=2) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)

    def upsert(self, session: SessionConfig) -> None:
        sessions = [item for item in self.load() if item.name != session.name]
        sessions.append(session)
        self.save(sorted(sessions, key=lambda item: item.name.casefold()))

    def merge(self, imported: list[SessionConfig], *, overwrite: bool = False) -> tuple[list[str], list[str]]:
        """Merge imported profiles, returning stored names and rename descriptions."""
        sessions = self.load()
        by_name = {item.name.casefold(): item for item in sessions}
        stored: list[str] = []
        renamed: list[str] = []
        for candidate in imported:
            original_name = candidate.name
            key = candidate.name.casefold()
            if key in by_name and overwrite:
                sessions = [item for item in sessions if item.name.casefold() != key]
            elif key in by_name:
                number = 2
                while f"{original_name} {number}".casefold() in by_name:
                    number += 1
                candidate = SessionConfig.from_dict({**candidate.to_dict(), "name": f"{original_name} {number}"})
                key = candidate.name.casefold()
                renamed.append(f"{original_name} → {candidate.name}")
            sessions.append(candidate)
            by_name[key] = candidate
            stored.append(candidate.name)
        self.save(sorted(sessions, key=lambda item: item.name.casefold()))
        return stored, renamed

    def delete(self, name: str) -> None:
        self.save([item for item in self.load() if item.name != name])
