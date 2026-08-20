from __future__ import annotations

import os
import stat
from base64 import b64encode
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath

import paramiko

from ..models import RemoteEntry, SessionConfig, normalize_remote_path
from ..resume import finish_partial, prepare_partial
from .base import BackendCapabilities, ProgressCallback, RemoteBackend


class UnknownHostKey(paramiko.SSHException):
    def __init__(self, hostname: str, key: paramiko.PKey) -> None:
        self.hostname = hostname
        self.key = key
        fingerprint = b64encode(sha256(key.asbytes()).digest()).decode("ascii").rstrip("=")
        super().__init__(f"Unknown host key for {hostname}: {key.get_name()} SHA256:{fingerprint}")


class RejectUnknownHostKeys(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client: paramiko.SSHClient, hostname: str, key: paramiko.PKey) -> None:
        raise UnknownHostKey(hostname, key)


class SFTPBackend(RemoteBackend):
    allow_missing_sftp = False
    capabilities = BackendCapabilities(
        download_resume=True,
        atomic_upload=True,
        recursive=True,
        permissions=True,
        symlinks=True,
    )

    def __init__(self, config: SessionConfig, password: str | None = None) -> None:
        self.config = config
        self.password = password
        self.client: paramiko.SSHClient | None = None
        self.sftp: paramiko.SFTPClient | None = None
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self.known_hosts = config_home / "debscp" / "known_hosts"

    def connect(self) -> None:
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        if self.known_hosts.exists():
            client.load_host_keys(str(self.known_hosts))
        client.set_missing_host_key_policy(RejectUnknownHostKeys())
        connection_host = self.config.host
        connection_port = self.config.port
        connection_user = self.config.username
        connection_key = self.config.key_file
        proxy_command = self.config.proxy_command
        ssh_config_path = Path.home() / ".ssh" / "config"
        if ssh_config_path.exists():
            ssh_config = paramiko.SSHConfig()
            with ssh_config_path.open(encoding="utf-8") as handle:
                ssh_config.parse(handle)
            options = ssh_config.lookup(self.config.host)
            connection_host = options.get("hostname", connection_host)
            connection_port = int(options.get("port", connection_port))
            connection_user = options.get("user", connection_user)
            identities = options.get("identityfile", [])
            if not connection_key and identities:
                connection_key = identities[0]
            proxy_command = proxy_command or options.get("proxycommand")
        if proxy_command == "none":
            proxy_command = None
        if self.config.jump_host and not proxy_command:
            proxy_command = f"ssh -W {connection_host}:{connection_port} {self.config.jump_host}"
        proxy = paramiko.ProxyCommand(proxy_command) if proxy_command else None
        try:
            client.connect(
                hostname=connection_host,
                port=connection_port,
                username=connection_user,
                password=self.password or None,
                key_filename=str(Path(connection_key).expanduser()) if connection_key else None,
                sock=proxy,
                allow_agent=True,
                look_for_keys=True,
                timeout=15,
                banner_timeout=15,
                auth_timeout=20,
            )
        except (OSError, paramiko.SSHException):
            client.close()
            raise
        self.client = client
        try:
            self.sftp = client.open_sftp()
        except (OSError, paramiko.SSHException):
            if not self.allow_missing_sftp:
                client.close()
                self.client = None
                raise

    def trust_host_key(self, hostname: str, key: paramiko.PKey) -> None:
        self.known_hosts.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        keys = paramiko.HostKeys()
        if self.known_hosts.exists():
            keys.load(str(self.known_hosts))
        keys.add(hostname, key.get_name(), key)
        keys.save(str(self.known_hosts))
        os.chmod(self.known_hosts, 0o600)

    def close(self) -> None:
        try:
            if self.sftp:
                self.sftp.close()
        finally:
            if self.client:
                self.client.close()
            self.sftp = None
            self.client = None

    def _connection(self) -> paramiko.SFTPClient:
        if not self.sftp:
            raise RuntimeError("Not connected")
        return self.sftp

    def listdir(self, path: str) -> list[RemoteEntry]:
        base = normalize_remote_path(path)
        entries = []
        for item in self._connection().listdir_attr(base):
            mode = int(item.st_mode or 0)
            entries.append(
                RemoteEntry(
                    name=item.filename,
                    path=str(PurePosixPath(base, item.filename)),
                    size=int(item.st_size or 0),
                    modified=datetime.fromtimestamp(item.st_mtime or 0, UTC).astimezone(),
                    mode=mode,
                    is_dir=stat.S_ISDIR(mode),
                    is_link=stat.S_ISLNK(mode),
                )
            )
        return sorted(entries, key=lambda entry: (not entry.is_dir, entry.name.casefold()))

    def download(self, remote: str, local: Path, progress: ProgressCallback | None = None) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        remote_path = normalize_remote_path(remote)
        temporary = local.with_name(local.name + ".debscp-part")
        details = self._connection().stat(remote_path)
        total = int(details.st_size or 0)
        identity = {"protocol": "sftp", "path": remote_path, "size": total, "mtime": int(details.st_mtime or 0)}
        offset = prepare_partial(temporary, identity, total)
        if offset == total:
            finish_partial(temporary, local)
            return
        with self._connection().open(remote_path, "rb") as source, temporary.open("ab") as destination:
            source.seek(offset)
            transferred = offset
            while chunk := source.read(262144):
                destination.write(chunk)
                transferred += len(chunk)
                if progress:
                    progress(transferred, total)
        finish_partial(temporary, local)

    def upload(self, local: Path, remote: str, progress: ProgressCallback | None = None) -> None:
        remote_path = normalize_remote_path(remote)
        temporary = remote_path + ".debscp-part"
        total = local.stat().st_size
        try:
            self._connection().remove(temporary)
        except OSError:
            pass
        with local.open("rb") as source, self._connection().open(temporary, "wb") as destination:
            transferred = 0
            while chunk := source.read(262144):
                destination.write(chunk)
                transferred += len(chunk)
                if progress:
                    progress(transferred, total)
        try:
            self._connection().posix_rename(temporary, remote_path)
        except OSError:
            try:
                self._connection().remove(remote_path)
            except OSError:
                pass
            self._connection().rename(temporary, remote_path)

    def mkdir(self, path: str) -> None:
        normalized = normalize_remote_path(path)
        try:
            self._connection().mkdir(normalized)
        except OSError:
            mode = int(self._connection().stat(normalized).st_mode or 0)
            if not stat.S_ISDIR(mode):
                raise

    def remove(self, path: str, *, directory: bool = False) -> None:
        normalized = normalize_remote_path(path)
        if normalized == "/":
            raise ValueError("Refusing to remove the remote root")
        if directory:
            self._connection().rmdir(normalized)
        else:
            self._connection().remove(normalized)

    def rename(self, source: str, destination: str) -> None:
        old_path, new_path = normalize_remote_path(source), normalize_remote_path(destination)
        try:
            self._connection().posix_rename(old_path, new_path)
        except OSError:
            self._connection().rename(old_path, new_path)
