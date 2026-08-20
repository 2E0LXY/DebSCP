from collections.abc import Callable

from ..models import SessionConfig
from .base import BackendCapabilities, RemoteBackend
from .ftp import FTPBackend
from .s3 import S3Backend
from .scp import SCPBackend
from .sftp import SFTPBackend, UnknownHostKey
from .webdav import WebDAVBackend


def create_backend(config: SessionConfig, password: str | None = None) -> RemoteBackend:
    protocol = config.protocol.lower()
    implementations: dict[str, Callable[[SessionConfig, str | None], RemoteBackend]] = {
        "sftp": SFTPBackend,
        "scp": SCPBackend,
        "ftp": FTPBackend,
        "ftps": FTPBackend,
        "ftps-implicit": FTPBackend,
        "webdav": WebDAVBackend,
        "webdavs": WebDAVBackend,
        "s3": S3Backend,
    }
    try:
        backend = implementations[protocol]
    except KeyError as exc:
        raise ValueError(f"Unsupported protocol: {protocol}") from exc
    return backend(config, password)


__all__ = [
    "BackendCapabilities",
    "FTPBackend",
    "RemoteBackend",
    "S3Backend",
    "SCPBackend",
    "SFTPBackend",
    "UnknownHostKey",
    "WebDAVBackend",
    "create_backend",
]
