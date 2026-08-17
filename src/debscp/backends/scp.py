from __future__ import annotations

from pathlib import Path

from scp import SCPClient

from ..models import SessionConfig
from .base import BackendCapabilities, ProgressCallback
from .sftp import SFTPBackend


class SCPBackend(SFTPBackend):
    """SCP data transfers with SFTP-backed browsing and file management."""

    capabilities = BackendCapabilities(resume=False, atomic_upload=False, recursive=True, permissions=True, symlinks=True)

    def __init__(self, config: SessionConfig, password: str | None = None) -> None:
        super().__init__(config, password)

    def _scp(self, progress: ProgressCallback | None = None) -> SCPClient:
        if not self.client:
            raise RuntimeError("Not connected")
        def report(_name: bytes, total: int, transferred: int, _peername: tuple[str, int]) -> None:
            if progress:
                progress(transferred, total)
        return SCPClient(self.client.get_transport(), progress4=report)

    def download(self, remote: str, local: Path, progress: ProgressCallback | None = None) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        with self._scp(progress) as client:
            client.get(remote, local_path=str(local), recursive=False, preserve_times=True)

    def upload(self, local: Path, remote: str, progress: ProgressCallback | None = None) -> None:
        with self._scp(progress) as client:
            client.put(str(local), remote_path=remote, recursive=False, preserve_times=True)

    def download_tree(self, remote: str, local: Path, progress: ProgressCallback | None = None) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        with self._scp(progress) as client:
            client.get(remote, local_path=str(local.parent), recursive=True, preserve_times=True)

    def upload_tree(self, local: Path, remote: str, progress: ProgressCallback | None = None) -> None:
        with self._scp(progress) as client:
            client.put(str(local), remote_path=remote, recursive=True, preserve_times=True)

