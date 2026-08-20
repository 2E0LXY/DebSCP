from __future__ import annotations

import builtins
from pathlib import Path
from typing import Self

from .backends import create_backend
from .backends.base import BackendCapabilities, RemoteBackend
from .editor import RemoteEditor
from .models import RemoteEntry, SessionConfig
from .session_store import SessionStore
from .sync import SyncAction, SyncDirection, SyncEngine


class Client:
    """Stable Python automation surface analogous to WinSCP's automation API."""

    def __init__(self, session: str | SessionConfig, password: str | None = None) -> None:
        if isinstance(session, str):
            try:
                session = next(item for item in SessionStore().load() if item.name == session)
            except StopIteration as exc:
                raise ValueError(f"Unknown session: {session}") from exc
        self.config = session
        self.backend: RemoteBackend = create_backend(session, password)

    def open(self) -> Self:
        self.backend.connect()
        return self

    def close(self) -> None:
        self.backend.close()

    def list(self, path: str = "/") -> list[RemoteEntry]:
        return self.backend.listdir(path)

    def get(self, remote: str, local: str | Path, *, recursive: bool = False) -> None:
        if recursive:
            self.backend.download_tree(remote, Path(local))
        else:
            self.backend.download(remote, Path(local))

    def put(self, local: str | Path, remote: str, *, recursive: bool = False) -> None:
        if recursive:
            self.backend.upload_tree(Path(local), remote)
        else:
            self.backend.upload(Path(local), remote)

    def remove(self, path: str, *, directory: bool = False) -> None:
        self.backend.remove(path, directory=directory)

    def remove_tree(self, path: str) -> None:
        self.backend.remove_tree(path)

    def mkdir(self, path: str) -> None:
        self.backend.mkdir(path)

    def rename(self, source: str, destination: str) -> None:
        self.backend.rename(source, destination)

    def edit(self, remote: str, editor: str | None = None) -> bool:
        return RemoteEditor(self.backend).edit(remote, editor)

    @property
    def capabilities(self) -> BackendCapabilities:
        return self.backend.capabilities

    def synchronize(
        self,
        local: str | Path,
        remote: str,
        direction: SyncDirection = SyncDirection.BOTH,
        *,
        apply: bool = False,
    ) -> builtins.list[SyncAction]:
        engine = SyncEngine(self.backend)
        actions = engine.compare(Path(local), remote, direction)
        if apply:
            engine.apply(actions, Path(local), remote)
        return actions

    def keep_up_to_date(
        self,
        local: str | Path,
        remote: str,
        *,
        interval: float = 5,
        stop_after: int | None = None,
    ) -> None:
        SyncEngine(self.backend).keep_up_to_date(Path(local), remote, interval=interval, stop_after=stop_after)

    def __enter__(self) -> Self:
        return self.open()

    def __exit__(self, *_: object) -> None:
        self.close()
