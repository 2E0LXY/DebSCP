import hashlib
from pathlib import Path

import pytest

from debscp.updater import (
    UpdateInfo,
    _release_info,
    download_update,
    installer_command,
    verify_debian_package,
    verify_package_file,
    version_tuple,
)


def release(version: str, content: bytes = b"package") -> dict:
    return {
        "tag_name": f"v{version}",
        "html_url": f"https://github.com/2E0LXY/DebSCP/releases/tag/v{version}",
        "assets": [
            {
                "name": f"debscp_{version}_all.deb",
                "browser_download_url": (
                    f"https://github.com/2E0LXY/DebSCP/releases/download/v{version}/debscp_{version}_all.deb"
                ),
                "size": len(content),
                "digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
            }
        ],
    }


def test_release_info_requires_newer_strict_semver_and_exact_asset() -> None:
    assert version_tuple("v2.10.3") == (2, 10, 3)
    assert _release_info(release("0.4.0"), "0.4.0") is None
    update = _release_info(release("0.5.0"), "0.4.0")
    assert update and (update.version, update.asset_name) == ("0.5.0", "debscp_0.5.0_all.deb")
    broken = release("0.5.0")
    broken["assets"][0]["digest"] = None
    with pytest.raises(ValueError, match="SHA-256"):
        _release_info(broken, "0.4.0")
    with pytest.raises(ValueError, match="Unsupported"):
        version_tuple("v0.5")


class Response:
    def __init__(self, content: bytes):
        self.content = content
        self.url = "https://release-assets.githubusercontent.com/github-production-release-asset/package"
        self.headers = {"Content-Length": str(len(content))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        yield self.content[:chunk_size]
        yield self.content[chunk_size:]


class Session:
    def __init__(self, content: bytes):
        self.content = content

    def get(self, *_args, **_kwargs):
        return Response(self.content)


def info_for(content: bytes) -> UpdateInfo:
    return _release_info(release("0.5.0", content), "0.4.0")  # type: ignore[return-value]


def test_download_update_verifies_size_and_digest(tmp_path: Path) -> None:
    content = b"verified package bytes"
    target = tmp_path / "debscp_0.5.0_all.deb"
    progress = []
    result = download_update(
        info_for(content),
        destination=target,
        session=Session(content),
        progress=lambda received, total: progress.append((received, total)),
    )
    assert result.read_bytes() == content
    assert progress[-1] == (len(content), len(content))
    assert not target.with_name(target.name + ".part").exists()


def test_download_update_removes_partial_on_checksum_failure(tmp_path: Path) -> None:
    expected, received = b"right package", b"wrong package"
    target = tmp_path / "debscp_0.5.0_all.deb"
    update = info_for(expected)
    update = UpdateInfo(
        update.version,
        update.tag,
        update.asset_name,
        update.download_url,
        len(received),
        update.sha256,
        update.release_url,
    )
    with pytest.raises(ValueError, match="SHA-256"):
        download_update(update, destination=target, session=Session(received))
    assert not target.exists()
    assert not target.with_name(target.name + ".part").exists()


def test_post_exit_verification_detects_a_changed_package(tmp_path: Path) -> None:
    content = b"original package"
    package = tmp_path / "update.deb"
    package.write_bytes(content)
    verify_package_file(package, len(content), hashlib.sha256(content).hexdigest())
    package.write_bytes(b"tampered package")
    with pytest.raises(ValueError, match="changed"):
        verify_package_file(package, len(content), hashlib.sha256(content).hexdigest())


def test_installer_uses_fixed_absolute_commands(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "update.deb"
    monkeypatch.setattr("debscp.updater.sys.platform", "linux")
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    assert installer_command(package) == [
        "/usr/bin/pkexec",
        "/usr/bin/apt-get",
        "install",
        "-y",
        str(package.resolve()),
    ]


def test_verify_debian_package_rejects_mismatched_metadata(monkeypatch, tmp_path: Path) -> None:
    class Result:
        stdout = "Package: other\nVersion: 0.5.0\nArchitecture: all\n"

    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr("debscp.updater.subprocess.run", lambda *_args, **_kwargs: Result())
    with pytest.raises(ValueError, match="metadata"):
        verify_debian_package(tmp_path / "update.deb", info_for(b"package"))


def test_verify_debian_package_accepts_dpkg_field_output(monkeypatch, tmp_path: Path) -> None:
    class Result:
        stdout = "Package: debscp\nVersion: 0.5.0\nArchitecture: all\n"

    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr("debscp.updater.subprocess.run", lambda *_args, **_kwargs: Result())
    verify_debian_package(tmp_path / "update.deb", info_for(b"package"))
