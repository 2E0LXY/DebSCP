# DebSCP

DebSCP is a native Linux desktop and command-line file transfer client inspired by the
workflow of WinSCP. It provides a dual-pane file manager, SFTP, SCP, FTP/FTPS,
WebDAV and S3 backends, synchronization, remote editing, saved workspaces,
automation, and Debian packaging without Wine or Windows libraries.

> **Project status:** v0.7.0 implements every capability category in the port
> matrix. It is still an independent implementation, so protocol edge cases
> and UI details can differ from WinSCP. See the [compatibility matrix](docs/PORT_STATUS.md).
> DebSCP is an independent project and is not affiliated with or endorsed by
> the WinSCP project.

## Features

- Native dark Linux GUI with matched local and remote file panes, compact menus,
  transfer toolbars, path controls, detailed file lists, and pane totals
- WinSCP-style startup login manager with searchable saved accounts, folders,
  workspaces, duplicate/rename/delete actions, and a separate Quick Connect path
- SFTP and SCP over SSH with password, SSH agent, or private-key authentication
- FTP, certificate-validated FTPS, WebDAV/HTTPS, Amazon S3 and S3-compatible storage
- Strict host-key checking with an explicit first-connection fingerprint prompt
- Upload/download queue with recursive operations, progress and errors
- Browse, create, rename, and recursively delete remote files and directories
- Saved profiles with passwords protected by the Linux system credential store
- WinSCP backup INI import with protocol, key, path, tunnel, proxy-command, and S3 mapping
- Bidirectional synchronization, reviewable checklists, and keep-up-to-date mode
- Conflict-checked remote editing and named include/exclude transfer presets
- Identity-validated resumable downloads and temporary-name atomic uploads where supported
- OpenSSH config, ProxyCommand and jump-host support
- Live connection tabs and saved workspaces
- Scriptable batch/JSON CLI and stable Python automation API
- Linux file-manager “Send with DebSCP” action
- Spanish and French gettext translations
- Reproducible Debian source package and `.deb` CI/release builds
- Background release checks and a flashing, one-click verified `.deb` updater

## Install a release

Download the `.deb` from [GitHub Releases](https://github.com/2E0LXY/DebSCP/releases) and run:

```sh
sudo apt install ./debscp_0.7.0_all.deb
```

Launch **DebSCP** from the application menu, run `debscp-gui`, or use the CLI:

```sh
debscp save production example.com --user deploy --key ~/.ssh/id_ed25519
debscp ls production /var/www
debscp get production /var/www/app.log ./app.log
debscp put production ./release.tar.gz /var/www/release.tar.gz
debscp sync production ./site /var/www --direction upload --apply
```

Imported or GUI-saved passwords are loaded automatically from the system
credential store. To override one for a script, pipe it rather than putting it
in process arguments:

```sh
printf '%s\n' "$SFTP_PASSWORD" | debscp ls production / --password-stdin
```

The CLI refuses unknown host keys. Review and trust a new server key once in
the GUI, after independently verifying its fingerprint.

## Automatic updates

DebSCP checks the latest stable GitHub Release shortly after startup and every
six hours while it remains open. When a newer `vMAJOR.MINOR.PATCH` tag has a
matching `debscp_VERSION_all.deb` asset, the **Update available** button in the
status bar flashes. The same button can be used to check manually.

Select the flashing button and confirm once. DebSCP downloads the package,
requires its size and GitHub-published SHA-256 digest to match, and verifies the
package name, version, and architecture with `dpkg-deb`. It then closes DebSCP;
a small detached helper re-verifies the file and launches `apt-get` through
PolicyKit only after the app has exited. The desktop's administrator approval
prompt completes the installation. Network failures do not interrupt
connections or transfers. Automatic installation is Linux-only and requires
the `pkexec`, `apt-get`, and `dpkg-deb` commands supplied by a normal Debian or
Ubuntu installation.

Version 0.5.0 is the first release containing the updater, so existing v0.4.0
installations need to install the v0.5.0 `.deb` manually once. Updates released
after v0.5.0 can then be installed from the flashing in-app button.

## Import sites from a WinSCP backup

On startup, DebSCP opens the **Login** account manager. Choose a saved account
and press **Login**, double-click it, or create and save a new site. Accounts can
be organised into folders, found with the search field, duplicated, renamed,
moved, and deleted. Passwords remain in the system credential store. Select
**Quick Connect** to open the transfer window without connecting; its compact
connection strip remains available for one-off tests.

Select **Import WinSCP…**, choose the `.ini` created by WinSCP's
**Tools → Export/Backup configuration** command, and review the import report.
From the command line:

```sh
debscp import-ini ~/Backups/WinSCP.ini
debscp --json import-ini ~/Backups/WinSCP.ini
```

Existing DebSCP profile names are preserved; imported collisions receive a
numeric suffix, matching WinSCP's import behavior. Use `--overwrite` to replace
same-named profiles instead. SFTP/SCP, explicit and implicit FTP/FTPS,
WebDAV/WebDAVS, S3 endpoints
and buckets, remote directories, private-key paths, local proxy commands, and
SSH tunnels are mapped. Unsupported proxy types are called out for manual
configuration.

Standard WinSCP session passwords are decrypted during import and immediately
saved under the final profile name in the operating system credential store.
They are never written to `sessions.json`, logs, terminal output, or the import
report. Backups protected by a WinSCP master password require separate master-
password support and are reported without importing the protected value.
Proxy passwords, key passphrases, and S3 session tokens are not imported.

For your first connection after importing, select the saved profile and press
**Connect**. DebSCP retrieves its password automatically; the password field can
remain blank. The CLI and Python API use the same stored credential. Providing
`--password-stdin` or an explicit API password overrides the saved value.

Windows `LocalDirectory` values are reported but not imported because drive
letters and UNC paths do not identify usable locations on Linux. Remote
directories are imported normally.

## Build and test

On Debian or Ubuntu:

```sh
sudo apt install build-essential devscripts debhelper dh-python \
  pybuild-plugin-pyproject python3-all python3-setuptools python3-boto3 \
  python3-keyring python3-paramiko python3-requests python3-scp python3-tk python3-pytest ruff
sudo apt install python3-defusedxml
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

- Passwords are excluded from profile JSON and protected by the operating system credential store.
- Profiles and DebSCP's `known_hosts` file are mode `0600`.
- System OpenSSH known-host keys are honored.
- Unknown keys are rejected until the user explicitly reviews and accepts the
  displayed key type and fingerprint.
- Remote paths are normalized and deleting `/` is blocked.
- WebDAV XML is parsed without entity expansion and oversized listings are rejected.
- Plain FTP is available for legacy servers but is unencrypted; prefer FTPS or SFTP.
- Resumed downloads are accepted only when server metadata still identifies the same source object.
- Automatic updates accept only the expected HTTPS GitHub release asset, enforce a 100 MiB limit,
  verify GitHub's SHA-256 digest and Debian package metadata, and invoke fixed absolute installer paths without a shell.

This is early software. Review changes carefully before using it against
important systems and keep independent backups.

## Design and WinSCP research

- [WinSCP architecture study](docs/WINSCP_ARCHITECTURE.md)
- [Port status and compatibility matrix](docs/PORT_STATUS.md)
- [DebSCP architecture](docs/ARCHITECTURE.md)
- [Automation reference](docs/AUTOMATION.md)
- [Contributing](CONTRIBUTING.md)

## License

DebSCP is licensed under the GNU General Public License v3.0. WinSCP is also
GPL-licensed, but its icon set has separate restrictions; DebSCP therefore uses
new project artwork and does not redistribute WinSCP icons or branding.
