from __future__ import annotations

import sys
from pathlib import Path

from .updater import UpdateInfo, launch_installer, verify_debian_package, verify_package_file, version_tuple


def main() -> int:
    if len(sys.argv) != 5:
        return 2
    package = Path(sys.argv[1]).resolve()
    version, size_text, sha256 = sys.argv[2:]
    try:
        version_tuple(version)
        size = int(size_text)
    except ValueError:
        return 2
    expected_name = f"debscp_{version}_all.deb"
    if package.name != expected_name:
        return 2
    # The parent keeps this pipe open until DebSCP has completely exited.
    sys.stdin.buffer.read()
    try:
        verify_package_file(package, size, sha256)
        info = UpdateInfo(version, f"v{version}", expected_name, "", size, sha256, "")
        verify_debian_package(package, info)
        launch_installer(package)
    except (OSError, RuntimeError, ValueError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
