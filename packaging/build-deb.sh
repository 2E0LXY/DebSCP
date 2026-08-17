#!/bin/sh
set -eu

command -v dpkg-buildpackage >/dev/null 2>&1 || {
  echo "dpkg-buildpackage is required (install build-essential and devscripts)" >&2
  exit 1
}
python3 tools/compile_translations.py
dpkg-buildpackage --no-sign
