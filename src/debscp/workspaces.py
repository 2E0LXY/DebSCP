from __future__ import annotations

import json
import os
from pathlib import Path


class WorkspaceStore:
    def __init__(self, path: Path | None = None) -> None:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self.path = path or config_home / "debscp" / "workspaces.json"

    def load(self) -> dict[str, list[str]]:
        if not self.path.exists():
            return {}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("workspaces.json must contain an object")
        return {str(name): [str(item) for item in sessions] for name, sessions in value.items()}

    def save(self, workspaces: dict[str, list[str]]) -> None:
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(workspaces, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)

    def set(self, name: str, sessions: list[str]) -> None:
        workspaces = self.load()
        workspaces[name] = list(dict.fromkeys(sessions))
        self.save(workspaces)

    def delete(self, name: str) -> None:
        workspaces = self.load()
        workspaces.pop(name, None)
        self.save(workspaces)
