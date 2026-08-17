from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urljoin, urlparse
from xml.etree import ElementTree

import requests

from ..models import RemoteEntry, SessionConfig, normalize_remote_path
from .base import BackendCapabilities, ProgressCallback, RemoteBackend


class WebDAVBackend(RemoteBackend):
    capabilities = BackendCapabilities(resume=True, atomic_upload=True, recursive=True)
    _DAV = "DAV:"

    def __init__(self, config: SessionConfig, password: str | None = None) -> None:
        self.config = config
        scheme = "https" if config.tls or config.protocol == "webdavs" else "http"
        self.base_url = config.endpoint_url or f"{scheme}://{config.host}:{config.port}/"
        self.session = requests.Session()
        self.session.auth = (config.username, password or "")

    def _url(self, path: str) -> str:
        normalized = normalize_remote_path(path)
        return urljoin(self.base_url.rstrip("/") + "/", quote(normalized.lstrip("/"), safe="/"))

    def connect(self) -> None:
        response = self.session.request("OPTIONS", self.base_url, timeout=20)
        response.raise_for_status()

    def close(self) -> None:
        self.session.close()

    def listdir(self, path: str) -> list[RemoteEntry]:
        base = normalize_remote_path(path)
        response = self.session.request("PROPFIND", self._url(base), headers={"Depth": "1"}, timeout=30)
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        entries: list[RemoteEntry] = []
        base_path = urlparse(self._url(base)).path.rstrip("/")
        for item in root.findall(f"{{{self._DAV}}}response"):
            href = unquote(item.findtext(f"{{{self._DAV}}}href", ""))
            href_path = urlparse(href).path.rstrip("/")
            if href_path == base_path:
                continue
            name = PurePosixPath(href_path).name
            prop = item.find(f".//{{{self._DAV}}}prop")
            if prop is None:
                continue
            resource_type = prop.find(f"{{{self._DAV}}}resourcetype")
            is_dir = resource_type is not None and resource_type.find(f"{{{self._DAV}}}collection") is not None
            modified_text = prop.findtext(f"{{{self._DAV}}}getlastmodified")
            modified = parsedate_to_datetime(modified_text).astimezone() if modified_text else datetime.fromtimestamp(0, UTC)
            entries.append(RemoteEntry(
                name=name, path=str(PurePosixPath(base, name)),
                size=int(prop.findtext(f"{{{self._DAV}}}getcontentlength", "0") or 0),
                modified=modified, mode=0, is_dir=is_dir,
            ))
        return sorted(entries, key=lambda entry: (not entry.is_dir, entry.name.casefold()))

    def download(self, remote: str, local: Path, progress: ProgressCallback | None = None) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        temporary = local.with_name(local.name + ".debscp-part")
        offset = temporary.stat().st_size if temporary.exists() else 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        response = self.session.get(self._url(remote), headers=headers, stream=True, timeout=60)
        if offset and response.status_code != 206:
            temporary.unlink(missing_ok=True)
            offset = 0
            response.close()
            response = self.session.get(self._url(remote), stream=True, timeout=60)
        response.raise_for_status()
        total = offset + int(response.headers.get("Content-Length", 0))
        transferred = offset
        with temporary.open("ab") as destination:
            for chunk in response.iter_content(262144):
                destination.write(chunk)
                transferred += len(chunk)
                if progress:
                    progress(transferred, total)
        temporary.replace(local)

    def upload(self, local: Path, remote: str, progress: ProgressCallback | None = None) -> None:
        remote_path = normalize_remote_path(remote)
        temporary = remote_path + ".debscp-part"
        total, transferred = local.stat().st_size, 0
        def stream():
            nonlocal transferred
            with local.open("rb") as source:
                while chunk := source.read(262144):
                    transferred += len(chunk)
                    if progress:
                        progress(transferred, total)
                    yield chunk
        response = self.session.put(self._url(temporary), data=stream(), timeout=120)
        response.raise_for_status()
        self._move(temporary, remote_path, overwrite=True)

    def mkdir(self, path: str) -> None:
        response = self.session.request("MKCOL", self._url(path), timeout=30)
        if response.status_code not in (201, 405):
            response.raise_for_status()

    def remove(self, path: str, *, directory: bool = False) -> None:
        normalized = normalize_remote_path(path)
        if normalized == "/":
            raise ValueError("Refusing to remove the remote root")
        self.session.delete(self._url(normalized), timeout=30).raise_for_status()

    def _move(self, source: str, destination: str, *, overwrite: bool) -> None:
        headers = {"Destination": self._url(destination), "Overwrite": "T" if overwrite else "F"}
        self.session.request("MOVE", self._url(source), headers=headers, timeout=30).raise_for_status()

    def rename(self, source: str, destination: str) -> None:
        self._move(source, destination, overwrite=False)

