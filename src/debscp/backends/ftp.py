from __future__ import annotations

# Plain FTP is an explicit legacy option; users are warned and FTPS is available.
import ftplib  # nosec
import socket
import ssl
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from ..models import RemoteEntry, SessionConfig, normalize_remote_path
from ..resume import finish_partial, prepare_partial
from .base import BackendCapabilities, ProgressCallback, RemoteBackend


class ImplicitFTP_TLS(ftplib.FTP_TLS):
    """FTP_TLS variant that negotiates TLS immediately on port 990."""

    def connect(
        self,
        host: str = "",
        port: int = 0,
        timeout: float = -999,
        source_address: tuple[str, int] | None = None,
    ) -> str:
        if self.sock is not None:
            raise ftplib.Error("Already connected")
        self.host = host or self.host
        self.port = port or self.port
        if timeout != -999:
            self.timeout = timeout
        if source_address is not None:
            self.source_address = source_address
        self.sock = socket.create_connection((self.host, self.port), self.timeout, source_address=self.source_address)
        self.af = self.sock.family
        self.sock = self.context.wrap_socket(self.sock, server_hostname=self.host)
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome


class FTPBackend(RemoteBackend):
    capabilities = BackendCapabilities(download_resume=True, atomic_upload=True, recursive=True)

    def __init__(self, config: SessionConfig, password: str | None = None) -> None:
        self.config = config
        self.password = password or ""
        self.ftp: ftplib.FTP | None = None

    def connect(self) -> None:
        connection: ftplib.FTP
        if self.config.protocol == "ftps-implicit":
            connection = ImplicitFTP_TLS(context=ssl.create_default_context())
        elif self.config.tls or self.config.protocol == "ftps":
            connection = ftplib.FTP_TLS(context=ssl.create_default_context())
        else:
            connection = ftplib.FTP()  # nosec
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
            entries.append(
                RemoteEntry(
                    name=name,
                    path=str(PurePosixPath(base, name)),
                    size=int(facts.get("size", 0)),
                    modified=timestamp,
                    mode=int(facts.get("unix.mode", "0"), 8),
                    is_dir=kind in ("dir", "cdir", "pdir"),
                )
            )
        return sorted(entries, key=lambda entry: (not entry.is_dir, entry.name.casefold()))

    def download(self, remote: str, local: Path, progress: ProgressCallback | None = None) -> None:
        remote_path = normalize_remote_path(remote)
        local.parent.mkdir(parents=True, exist_ok=True)
        temporary = local.with_name(local.name + ".debscp-part")
        connection = self._connection()
        connection.voidcmd("TYPE I")
        total = connection.size(remote_path) or 0
        try:
            modified = connection.sendcmd(f"MDTM {remote_path}")
        except ftplib.Error:
            modified = None
        identity = {"protocol": "ftp", "path": remote_path, "size": total, "modified": modified} if modified else None
        offset = prepare_partial(temporary, identity, total)
        if offset == total:
            finish_partial(temporary, local)
            return
        transferred = offset
        with temporary.open("ab") as destination:

            def consume(chunk: bytes) -> None:
                nonlocal transferred
                destination.write(chunk)
                transferred += len(chunk)
                if progress:
                    progress(transferred, total)

            connection.retrbinary(f"RETR {remote_path}", consume, rest=offset or None)
        finish_partial(temporary, local)

    def upload(self, local: Path, remote: str, progress: ProgressCallback | None = None) -> None:
        remote_path = normalize_remote_path(remote)
        temporary = remote_path + ".debscp-part"
        try:
            self._connection().delete(temporary)
        except ftplib.Error:
            pass
        total, transferred = local.stat().st_size, 0
        with local.open("rb") as source:

            def report(chunk: bytes) -> None:
                nonlocal transferred
                transferred += len(chunk)
                if progress:
                    progress(transferred, total)

            self._connection().storbinary(f"STOR {temporary}", source, callback=report)
        try:
            self._connection().delete(remote_path)
        except ftplib.Error:
            pass
        self._connection().rename(temporary, remote_path)

    def mkdir(self, path: str) -> None:
        connection = self._connection()
        normalized = normalize_remote_path(path)
        try:
            connection.mkd(normalized)
        except ftplib.Error as error:
            current = connection.pwd()
            try:
                connection.cwd(normalized)
            except ftplib.Error:
                raise error
            finally:
                connection.cwd(current)

    def remove(self, path: str, *, directory: bool = False) -> None:
        normalized = normalize_remote_path(path)
        if normalized == "/":
            raise ValueError("Refusing to remove the remote root")
        (self._connection().rmd if directory else self._connection().delete)(normalized)

    def rename(self, source: str, destination: str) -> None:
        self._connection().rename(normalize_remote_path(source), normalize_remote_path(destination))
