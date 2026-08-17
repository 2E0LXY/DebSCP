# DebSCP

DebSCP is a native Linux desktop and command-line SFTP client inspired by the
workflow of WinSCP. It provides a dual-pane file manager, saved session
profiles, strict SSH host-key verification, queued transfers, and Debian
packaging without Wine or Windows libraries.

> **Project status:** v0.1.0 is an alpha-quality, SFTP-first foundation—not a
> feature-complete WinSCP port. See the [compatibility matrix](docs/PORT_STATUS.md).
> DebSCP is an independent project and is not affiliated with or endorsed by
> the WinSCP project.

## Features

- Native Linux GUI with local and remote file panes
- SFTP over SSH with password, SSH agent, or private-key authentication
- Strict host-key checking with an explicit first-connection fingerprint prompt
- Upload/download queue with progress and errors
- Browse, create, rename, and delete remote files and empty directories
- Saved profiles that deliberately never store passwords
- Scriptable CLI for listing and file operations
- Reproducible Debian source package and `.deb` CI/release builds

## Install a release

Download the `.deb` from the repository's Releases page and run:

```sh
sudo apt install ./debscp_0.1.0_all.deb
```

Launch **DebSCP** from the application menu, run `debscp-gui`, or use the CLI:

```sh
debscp save production example.com --user deploy --key ~/.ssh/id_ed25519
debscp ls production /var/www
debscp get production /var/www/app.log ./app.log
debscp put production ./release.tar.gz /var/www/release.tar.gz
```

For password authentication in scripts, pipe the password rather than putting
it in process arguments:

```sh
printf '%s\n' "$SFTP_PASSWORD" | debscp ls production / --password-stdin
```

The CLI refuses unknown host keys. Review and trust a new server key once in
the GUI, after independently verifying its fingerprint.

## Build and test

On Debian or Ubuntu:

```sh
sudo apt install build-essential devscripts debhelper dh-python \
  pybuild-plugin-pyproject python3-all python3-setuptools python3-paramiko \
  python3-tk python3-pytest ruff
python3 -m pytest
ruff check src tests
./packaging/build-deb.sh
```

The resulting package is written to the parent directory. GitHub Actions runs
the same tests and package build; pushing a `v*` tag creates a GitHub Release
and attaches the `.deb`.

For local development outside Debian packaging:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
debscp-gui
```

## Security model

- Passwords are memory-only and are never written to profile storage.
- Profiles and DebSCP's `known_hosts` file are mode `0600`.
- System OpenSSH known-host keys are honored.
- Unknown keys are rejected until the user explicitly reviews and accepts the
  displayed key type and fingerprint.
- Remote paths are normalized and deleting `/` is blocked.

This is early software. Review changes carefully before using it against
important systems and keep independent backups.

## Design and WinSCP research

- [WinSCP architecture study](docs/WINSCP_ARCHITECTURE.md)
- [Port status and compatibility matrix](docs/PORT_STATUS.md)
- [DebSCP architecture](docs/ARCHITECTURE.md)
- [Contributing](CONTRIBUTING.md)

## License

DebSCP is licensed under the GNU General Public License v3.0. WinSCP is also
GPL-licensed, but its icon set has separate restrictions; DebSCP therefore uses
new project artwork and does not redistribute WinSCP icons or branding.
