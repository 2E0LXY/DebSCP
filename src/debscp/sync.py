from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

from .backends.base import RemoteBackend
from .models import RemoteEntry, normalize_remote_path
from .policies import TransferPreset


class SyncDirection(str, Enum):
    UPLOAD = "upload"
    DOWNLOAD = "download"
    BOTH = "both"


class SyncOperation(str, Enum):
    UPLOAD = "upload"
    DOWNLOAD = "download"
    MKDIR_LOCAL = "mkdir-local"
    MKDIR_REMOTE = "mkdir-remote"
    DELETE_LOCAL = "delete-local"
    DELETE_REMOTE = "delete-remote"


@dataclass(frozen=True, slots=True)
class SyncAction:
    operation: SyncOperation
    relative_path: str
    reason: str


class SyncEngine:
    def __init__(self, backend: RemoteBackend) -> None:
        self.backend = backend

    def _remote_tree(self, root: str) -> dict[str, RemoteEntry]:
        result: dict[str, RemoteEntry] = {}
        def visit(path: str, relative: str = "") -> None:
            for entry in self.backend.listdir(path):
                child = f"{relative}/{entry.name}".lstrip("/")
                result[child] = entry
                if entry.is_dir:
                    visit(entry.path, child)
        visit(normalize_remote_path(root))
        return result

    @staticmethod
    def _local_tree(root: Path) -> dict[str, Path]:
        return {item.relative_to(root).as_posix(): item for item in root.rglob("*")}

    def compare(
        self,
        local_root: Path,
        remote_root: str,
        direction: SyncDirection = SyncDirection.BOTH,
        preset: TransferPreset | None = None,
        *,
        delete: bool = False,
    ) -> list[SyncAction]:
        policy = preset or TransferPreset("Default")
        local = {key: value for key, value in self._local_tree(local_root).items() if policy.matches(key)}
        remote = {key: value for key, value in self._remote_tree(remote_root).items() if policy.matches(key)}
        actions: list[SyncAction] = []
        for relative in sorted(set(local) | set(remote)):
            local_item, remote_item = local.get(relative), remote.get(relative)
            if local_item and not remote_item:
                if direction in (SyncDirection.UPLOAD, SyncDirection.BOTH):
                    operation = SyncOperation.MKDIR_REMOTE if local_item.is_dir() else SyncOperation.UPLOAD
                    actions.append(SyncAction(operation, relative, "missing remotely"))
                elif delete and direction == SyncDirection.DOWNLOAD:
                    actions.append(SyncAction(SyncOperation.DELETE_LOCAL, relative, "not present remotely"))
            elif remote_item and not local_item:
                if direction in (SyncDirection.DOWNLOAD, SyncDirection.BOTH):
                    operation = SyncOperation.MKDIR_LOCAL if remote_item.is_dir else SyncOperation.DOWNLOAD
                    actions.append(SyncAction(operation, relative, "missing locally"))
                elif delete and direction == SyncDirection.UPLOAD:
                    actions.append(SyncAction(SyncOperation.DELETE_REMOTE, relative, "not present locally"))
            elif local_item and remote_item and not local_item.is_dir() and not remote_item.is_dir:
                local_mtime = local_item.stat().st_mtime
                different = local_item.stat().st_size != remote_item.size or abs(local_mtime - remote_item.modified.timestamp()) > 2
                if different:
                    if direction == SyncDirection.UPLOAD or (direction == SyncDirection.BOTH and local_mtime >= remote_item.modified.timestamp()):
                        actions.append(SyncAction(SyncOperation.UPLOAD, relative, "local file is newer or different"))
                    else:
                        actions.append(SyncAction(SyncOperation.DOWNLOAD, relative, "remote file is newer or different"))
        return actions

    def apply(self, actions: list[SyncAction], local_root: Path, remote_root: str) -> None:
        remote_base = PurePosixPath(normalize_remote_path(remote_root))
        for action in actions:
            local_path = local_root / action.relative_path
            remote_path = str(remote_base / action.relative_path)
            if action.operation == SyncOperation.UPLOAD:
                self.backend.upload(local_path, remote_path)
            elif action.operation == SyncOperation.DOWNLOAD:
                self.backend.download(remote_path, local_path)
            elif action.operation == SyncOperation.MKDIR_LOCAL:
                local_path.mkdir(parents=True, exist_ok=True)
            elif action.operation == SyncOperation.MKDIR_REMOTE:
                self.backend.mkdir(remote_path)
            elif action.operation == SyncOperation.DELETE_LOCAL:
                local_path.rmdir() if local_path.is_dir() else local_path.unlink()
            elif action.operation == SyncOperation.DELETE_REMOTE:
                entry = next((item for item in self.backend.listdir(str(PurePosixPath(remote_path).parent)) if item.path == remote_path), None)
                self.backend.remove(remote_path, directory=bool(entry and entry.is_dir))

    def keep_up_to_date(
        self,
        local_root: Path,
        remote_root: str,
        interval: float = 5,
        preset: TransferPreset | None = None,
        stop_after: int | None = None,
    ) -> None:
        iterations = 0
        while stop_after is None or iterations < stop_after:
            actions = self.compare(local_root, remote_root, SyncDirection.UPLOAD, preset)
            self.apply(actions, local_root, remote_root)
            iterations += 1
            time.sleep(interval)

