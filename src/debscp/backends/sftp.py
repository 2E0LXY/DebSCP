from __future__ import annotations

import os
import stat
from base64 import b64encode
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath

import paramiko

from ..models import RemoteEntry, SessionConfig, normalize_remote_path
from .base import ProgressCallback, RemoteBackend


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
        try:
            client.connect(
                hostname=self.config.host,
                port=self.config.port,
                username=self.config.username,
                password=self.password or None,
                key_filename=str(Path(self.config.key_file).expanduser()) if self.config.key_file else None,
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
        self.sftp = client.open_sftp()

    def trust_host_key(self, hostname: str, key: paramiko.PKey) -> None:
        self.known_hosts.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        keys = paramiko.HostKeys()
        if self.known_hosts.exists():
            keys.load(str(self.known_hosts))
        keys.add(hostname, key.get_name(), key)
        keys.save(str(self.known_hosts))
        os.chmod(self.known_hosts, 0o600)

    def close(self) -> None:
        if self.sftp:
            self.sftp.close()
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
        self._connection().get(normalize_remote_path(remote), str(local), callback=progress)

    def upload(self, local: Path, remote: str, progress: ProgressCallback | None = None) -> None:
        self._connection().put(str(local), normalize_remote_path(remote), callback=progress, confirm=True)

    def mkdir(self, path: str) -> None:
        self._connection().mkdir(normalize_remote_path(path))

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
