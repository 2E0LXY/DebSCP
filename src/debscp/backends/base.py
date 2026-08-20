from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from ..models import RemoteEntry

ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True, slots=True)
class BackendCapabilities:
    download_resume: bool = False
    upload_resume: bool = False
    atomic_upload: bool = False
    recursive: bool = False
    permissions: bool = False
    symlinks: bool = False


DEFAULT_CAPABILITIES = BackendCapabilities()


class RemoteBackend(ABC):
    capabilities = DEFAULT_CAPABILITIES

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def listdir(self, path: str) -> list[RemoteEntry]: ...

    @abstractmethod
    def download(self, remote: str, local: Path, progress: ProgressCallback | None = None) -> None: ...

    @abstractmethod
    def upload(self, local: Path, remote: str, progress: ProgressCallback | None = None) -> None: ...

    @abstractmethod
    def mkdir(self, path: str) -> None: ...

    @abstractmethod
    def remove(self, path: str, *, directory: bool = False) -> None: ...

    @abstractmethod
    def rename(self, source: str, destination: str) -> None: ...

    def download_tree(self, remote: str, local: Path, progress: ProgressCallback | None = None) -> None:
        local.mkdir(parents=True, exist_ok=True)
        for entry in self.listdir(remote):
            destination = local / entry.name
            if entry.is_dir:
                self.download_tree(entry.path, destination, progress)
            else:
                self.download(entry.path, destination, progress)

    def upload_tree(self, local: Path, remote: str, progress: ProgressCallback | None = None) -> None:
        self.mkdir(remote)
        for item in local.iterdir():
            destination = remote.rstrip("/") + "/" + item.name
            if item.is_dir():
                self.upload_tree(item, destination, progress)
            else:
                self.upload(item, destination, progress)

    def remove_tree(self, remote: str) -> None:
        for entry in self.listdir(remote):
            if entry.is_dir:
                self.remove_tree(entry.path)
            else:
                self.remove(entry.path)
        self.remove(remote, directory=True)

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
