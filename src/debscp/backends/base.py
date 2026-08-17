from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Self

from ..models import RemoteEntry

ProgressCallback = Callable[[int, int], None]


class RemoteBackend(ABC):
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

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
