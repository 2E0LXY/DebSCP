from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from .backends.base import RemoteBackend


class RemoteEditConflict(RuntimeError):
    pass


class RemoteEditor:
    def __init__(self, backend: RemoteBackend) -> None:
        self.backend = backend

    def edit(self, remote_path: str, editor: str | None = None) -> bool:
        parent = str(PurePosixPath(remote_path).parent)
        original = next(item for item in self.backend.listdir(parent) if item.path == remote_path)
        with tempfile.TemporaryDirectory(prefix="debscp-edit-") as directory:
            local = Path(directory) / PurePosixPath(remote_path).name
            self.backend.download(remote_path, local)
            before = local.stat().st_mtime_ns
            command = editor or os.environ.get("VISUAL") or os.environ.get("EDITOR") or "xdg-open"
            subprocess.run([*shlex.split(command), str(local)], check=True)
            if local.stat().st_mtime_ns == before:
                return False
            current = next(item for item in self.backend.listdir(parent) if item.path == remote_path)
            if current.size != original.size or current.modified != original.modified:
                raise RemoteEditConflict(f"Remote file changed while editing: {remote_path}")
            self.backend.upload(local, remote_path)
            return True

