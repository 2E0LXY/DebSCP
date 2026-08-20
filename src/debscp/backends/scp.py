from __future__ import annotations

import shlex
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from scp import SCPClient

from ..models import RemoteEntry, SessionConfig, normalize_remote_path
from .base import BackendCapabilities, ProgressCallback
from .sftp import SFTPBackend


class SCPBackend(SFTPBackend):
    """SCP transfers with SFTP or Linux SSH-command file management."""

    capabilities = BackendCapabilities(recursive=True, permissions=True, symlinks=True)
    allow_missing_sftp = True

    def __init__(self, config: SessionConfig, password: str | None = None) -> None:
        super().__init__(config, password)

    def _exec(self, command: str) -> bytes:
        if not self.client:
            raise RuntimeError("Not connected")
        _stdin, stdout, stderr = self.client.exec_command(command, timeout=30)
        status = stdout.channel.recv_exit_status()
        error = stderr.read().decode("utf-8", "replace").strip()
        if status:
            raise OSError(error or f"Remote command failed with exit status {status}")
        return stdout.read()

    def listdir(self, path: str) -> list[RemoteEntry]:
        if self.sftp:
            return super().listdir(path)
        base = normalize_remote_path(path)
        quoted = shlex.quote(base)
        output = self._exec(
            f"find {quoted} -mindepth 1 -maxdepth 1 -printf '%f\\0%s\\0%T@\\0%m\\0%y\\0'",
        )
        fields = output.decode("utf-8", "surrogateescape").split("\0")
        entries: list[RemoteEntry] = []
        for index in range(0, len(fields) - 1, 5):
            name, size, modified, mode, kind = fields[index : index + 5]
            entries.append(
                RemoteEntry(
                    name=name,
                    path=str(PurePosixPath(base, name)),
                    size=int(size),
                    modified=datetime.fromtimestamp(float(modified), UTC).astimezone(),
                    mode=int(mode, 8),
                    is_dir=kind == "d",
                    is_link=kind == "l",
                )
            )
        return sorted(entries, key=lambda entry: (not entry.is_dir, entry.name.casefold()))

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

    def mkdir(self, path: str) -> None:
        if self.sftp:
            super().mkdir(path)
        else:
            self._exec(f"mkdir -p -- {shlex.quote(normalize_remote_path(path))}")

    def remove(self, path: str, *, directory: bool = False) -> None:
        normalized = normalize_remote_path(path)
        if normalized == "/":
            raise ValueError("Refusing to remove the remote root")
        if self.sftp:
            super().remove(normalized, directory=directory)
        else:
            command = "rmdir" if directory else "rm"
            self._exec(f"{command} -- {shlex.quote(normalized)}")

    def rename(self, source: str, destination: str) -> None:
        if self.sftp:
            super().rename(source, destination)
        else:
            old_path = shlex.quote(normalize_remote_path(source))
            new_path = shlex.quote(normalize_remote_path(destination))
            self._exec(f"mv -- {old_path} {new_path}")
