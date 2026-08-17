from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(slots=True)
class TransferPreset:
    name: str
    include: list[str] = field(default_factory=lambda: ["*"])
    exclude: list[str] = field(default_factory=list)
    preserve_times: bool = True
    recursive: bool = True
    overwrite: bool = True

    def matches(self, relative_path: str) -> bool:
        path = relative_path.replace(os.sep, "/")
        included = any(fnmatch.fnmatch(path, pattern) for pattern in self.include)
        excluded = any(fnmatch.fnmatch(path, pattern) for pattern in self.exclude)
        return included and not excluded


class PresetStore:
    def __init__(self, path: Path | None = None) -> None:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self.path = path or config_home / "debscp" / "presets.json"

    def load(self) -> list[TransferPreset]:
        if not self.path.exists():
            return [TransferPreset("Default")]
        content = json.loads(self.path.read_text(encoding="utf-8"))
        return [TransferPreset(**item) for item in content]

    def save(self, presets: list[TransferPreset]) -> None:
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps([asdict(item) for item in presets], indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)

