from __future__ import annotations

import hashlib
import hmac
import os
import re

# Subprocess use below is restricted to fixed absolute system executables.
import subprocess  # nosec B404
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

REPOSITORY = "2E0LXY/DebSCP"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
API_VERSION = "2026-03-10"
MAX_PACKAGE_SIZE = 100 * 1024 * 1024
_VERSION_RE = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_DIGEST_RE = re.compile(r"^sha256:([0-9a-fA-F]{64})$")


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    tag: str
    asset_name: str
    download_url: str
    size: int
    sha256: str
    release_url: str


def version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"Unsupported release version: {value!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _release_info(payload: object, current_version: str) -> UpdateInfo | None:
    if not isinstance(payload, dict):
        raise TypeError("GitHub returned an invalid release response")
    tag = payload.get("tag_name")
    if not isinstance(tag, str):
        raise TypeError("The latest GitHub release has no version tag")
    latest = version_tuple(tag)
    if latest <= version_tuple(current_version):
        return None
    version = ".".join(str(part) for part in latest)
    expected_name = f"debscp_{version}_all.deb"
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise TypeError("The latest release has no downloadable assets")
    matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == expected_name]
    if len(matches) != 1:
        raise ValueError(f"The latest release does not contain exactly one {expected_name} package")
    asset = matches[0]
    url, size, digest = asset.get("browser_download_url"), asset.get("size"), asset.get("digest")
    if not isinstance(url, str) or not _trusted_download_url(url):
        raise ValueError("The release package has an untrusted download URL")
    if not isinstance(size, int) or not 0 < size <= MAX_PACKAGE_SIZE:
        raise ValueError("The release package has an invalid size")
    if not isinstance(digest, str) or not (digest_match := _DIGEST_RE.fullmatch(digest)):
        raise ValueError("The release package does not publish a valid SHA-256 digest")
    release_url = payload.get("html_url")
    if not isinstance(release_url, str) or not release_url.startswith("https://github.com/"):
        release_url = f"https://github.com/{REPOSITORY}/releases/tag/{tag}"
    return UpdateInfo(version, tag, expected_name, url, size, digest_match.group(1).lower(), release_url)


def check_for_update(current_version: str, *, session: requests.Session | None = None) -> UpdateInfo | None:
    client = session or requests.Session()
    response = client.get(
        LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": f"DebSCP/{current_version}",
        },
        timeout=15,
    )
    response.raise_for_status()
    return _release_info(response.json(), current_version)


def _trusted_download_url(url: str, *, redirected: bool = False) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    host = (parsed.hostname or "").lower()
    if redirected:
        return host == "github.com" or host.endswith(".githubusercontent.com")
    expected_prefix = f"/{REPOSITORY}/releases/download/"
    return host == "github.com" and parsed.path.startswith(expected_prefix)


def _cache_directory() -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "debscp" / "updates"


def download_update(
    info: UpdateInfo,
    *,
    destination: Path | None = None,
    session: requests.Session | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    target = destination or (_cache_directory() / info.asset_name)
    target = target.expanduser().resolve()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    client = session or requests.Session()
    try:
        with client.get(
            info.download_url,
            headers={"Accept": "application/octet-stream", "User-Agent": f"DebSCP/{info.version}"},
            stream=True,
            timeout=(15, 120),
        ) as response:
            response.raise_for_status()
            if not _trusted_download_url(response.url, redirected=True):
                raise ValueError("GitHub redirected the update to an untrusted host")
            header_size = response.headers.get("Content-Length")
            if header_size is not None and int(header_size) != info.size:
                raise ValueError("The downloaded package size does not match the release metadata")
            digest = hashlib.sha256()
            received = 0
            with partial.open("wb") as package:
                os.chmod(partial, 0o600)
                for chunk in response.iter_content(chunk_size=1024 * 128):
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > info.size or received > MAX_PACKAGE_SIZE:
                        raise ValueError("The downloaded package is larger than expected")
                    package.write(chunk)
                    digest.update(chunk)
                    if progress:
                        progress(received, info.size)
            if received != info.size:
                raise ValueError("The downloaded package is incomplete")
            if not hmac.compare_digest(digest.hexdigest(), info.sha256):
                raise ValueError("The downloaded package failed SHA-256 verification")
        partial.replace(target)
        return target
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def verify_debian_package(package: Path, info: UpdateInfo) -> None:
    dpkg_deb = "/usr/bin/dpkg-deb"
    if not Path(dpkg_deb).is_file():
        raise RuntimeError("dpkg-deb is required to validate the downloaded update")
    # The executable is the fixed /usr/bin/dpkg-deb path.
    result = subprocess.run(  # nosec B603
        [dpkg_deb, "--field", str(package), "Package", "Version", "Architecture"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    fields = dict(line.split(":", 1) for line in result.stdout.splitlines() if ":" in line)
    if (
        fields.get("Package", "").strip() != "debscp"
        or fields.get("Version", "").strip() != info.version
        or fields.get("Architecture", "").strip() != "all"
    ):
        raise ValueError("The downloaded Debian package metadata does not match this DebSCP release")


def verify_package_file(package: Path, expected_size: int, expected_sha256: str) -> None:
    if not 0 < expected_size <= MAX_PACKAGE_SIZE or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise ValueError("Invalid expected package metadata")
    digest = hashlib.sha256()
    received = 0
    with package.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 128), b""):
            received += len(chunk)
            if received > expected_size or received > MAX_PACKAGE_SIZE:
                raise ValueError("The update package is larger than expected")
            digest.update(chunk)
    if received != expected_size or not hmac.compare_digest(digest.hexdigest(), expected_sha256.lower()):
        raise ValueError("The update package changed after download verification")


def installer_command(package: Path) -> list[str]:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("Automatic .deb installation is available only on Linux")
    pkexec, apt_get = "/usr/bin/pkexec", "/usr/bin/apt-get"
    if not Path(pkexec).is_file():
        raise RuntimeError("PolicyKit pkexec is required for automatic updates")
    if not Path(apt_get).is_file():
        raise RuntimeError("apt-get is required for automatic updates")
    return [pkexec, apt_get, "install", "-y", str(package.resolve())]


def launch_installer(package: Path) -> subprocess.Popen[bytes]:
    # installer_command permits only fixed absolute executables.
    return subprocess.Popen(  # nosec B603
        installer_command(package),
        close_fds=True,
        start_new_session=True,
    )


def launch_installer_after_exit(package: Path, info: UpdateInfo) -> subprocess.Popen[bytes]:
    python = "/usr/bin/python3"
    installer_command(package)
    if not sys.platform.startswith("linux"):
        raise RuntimeError("Automatic .deb installation is available only on Linux")
    if not Path(python).is_file():
        raise RuntimeError("The system Python interpreter is required for automatic updates")
    command = [
        python,
        "-m",
        "debscp.update_helper",
        str(package.resolve()),
        info.version,
        str(info.size),
        info.sha256,
    ]
    # The fixed interpreter runs DebSCP's argument-validating helper. It waits for stdin EOF.
    return subprocess.Popen(  # nosec B603
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )
