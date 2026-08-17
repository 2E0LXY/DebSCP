from __future__ import annotations

import ftplib
import ssl
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from ..models import RemoteEntry, SessionConfig, normalize_remote_path
from .base import BackendCapabilities, ProgressCallback, RemoteBackend


class FTPBackend(RemoteBackend):
    capabilities = BackendCapabilities(resume=True, atomic_upload=True, recursive=True)

    def __init__(self, config: SessionConfig, password: str | None = None) -> None:
        self.config = config
        self.password = password or ""
        self.ftp: ftplib.FTP | None = None

    def connect(self) -> None:
        if self.config.tls or self.config.protocol == "ftps":
            connection = ftplib.FTP_TLS(context=ssl.create_default_context())
        else:
            connection = ftplib.FTP()
        connection.connect(self.config.host, self.config.port, timeout=20)
        connection.login(self.config.username, self.password)
        if isinstance(connection, ftplib.FTP_TLS):
            connection.prot_p()
        self.ftp = connection

    def _connection(self) -> ftplib.FTP:
        if not self.ftp:
            raise RuntimeError("Not connected")
        return self.ftp

    def close(self) -> None:
        if self.ftp:
            try:
                self.ftp.quit()
            except (OSError, ftplib.Error):
                self.ftp.close()
        self.ftp = None

    def listdir(self, path: str) -> list[RemoteEntry]:
        base = normalize_remote_path(path)
        entries: list[RemoteEntry] = []
        for name, facts in self._connection().mlsd(base, facts=["type", "size", "modify", "unix.mode"]):
            if name in (".", ".."):
                continue
            modified = facts.get("modify", "19700101000000")
            try:
                timestamp = datetime.strptime(modified[:14], "%Y%m%d%H%M%S").replace(tzinfo=UTC).astimezone()
            except ValueError:
                timestamp = datetime.fromtimestamp(0, UTC).astimezone()
            kind = facts.get("type", "file")
            entries.append(RemoteEntry(
                name=name, path=str(PurePosixPath(base, name)), size=int(facts.get("size", 0)),
                modified=timestamp, mode=int(facts.get("unix.mode", "0"), 8), is_dir=kind in ("dir", "cdir", "pdir"),
            ))
        return sorted(entries, key=lambda entry: (not entry.is_dir, entry.name.casefold()))

    def download(self, remote: str, local: Path, progress: ProgressCallback | None = None) -> None:
        remote_path = normalize_remote_path(remote)
        local.parent.mkdir(parents=True, exist_ok=True)
        temporary = local.with_name(local.name + ".debscp-part")
        offset = temporary.stat().st_size if temporary.exists() else 0
        total = self._connection().size(remote_path) or 0
        if offset > total:
            temporary.unlink()
            offset = 0
        transferred = offset
        with temporary.open("ab") as destination:
            def consume(chunk: bytes) -> None:
                nonlocal transferred
                destination.write(chunk)
                transferred += len(chunk)
                if progress:
                    progress(transferred, total)
            self._connection().retrbinary(f"RETR {remote_path}", consume, rest=offset or None)
        temporary.replace(local)

    def upload(self, local: Path, remote: str, progress: ProgressCallback | None = None) -> None:
        remote_path = normalize_remote_path(remote)
        temporary = remote_path + ".debscp-part"
        try:
            offset = self._connection().size(temporary) or 0
        except ftplib.Error:
            offset = 0
        total, transferred = local.stat().st_size, offset
        with local.open("rb") as source:
            source.seek(offset)
            def report(chunk: bytes) -> None:
                nonlocal transferred
                transferred += len(chunk)
                if progress:
                    progress(transferred, total)
            self._connection().storbinary(f"STOR {temporary}", source, callback=report, rest=offset or None)
        try:
            self._connection().delete(remote_path)
        except ftplib.Error:
            pass
        self._connection().rename(temporary, remote_path)

    def mkdir(self, path: str) -> None:
        self._connection().mkd(normalize_remote_path(path))

    def remove(self, path: str, *, directory: bool = False) -> None:
        normalized = normalize_remote_path(path)
        if normalized == "/":
            raise ValueError("Refusing to remove the remote root")
        (self._connection().rmd if directory else self._connection().delete)(normalized)

    def rename(self, source: str, destination: str) -> None:
        self._connection().rename(normalize_remote_path(source), normalize_remote_path(destination))

