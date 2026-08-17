# Contributing

Use Python 3.11 or newer. Install the project and development tools, then run:

```sh
python3 -m pip install -e . pytest ruff
ruff check src tests
pytest
```

Keep protocol code behind `RemoteBackend`. Do not save passwords or silently
accept SSH host keys. Add tests for path handling, destructive operations, and
all new backend behavior. Update `docs/PORT_STATUS.md` when compatibility
changes.

WinSCP is GPL-licensed, but its icon set has separate restrictions. Do not copy
WinSCP artwork or branding into DebSCP. Contributions derived from GPL code must
preserve the applicable notices and license obligations.

