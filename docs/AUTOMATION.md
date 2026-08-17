# Automation reference

## CLI contract

Use `--json` before the subcommand for machine-readable results:

```sh
debscp --json sessions
debscp --json ls production /srv/app
debscp --json sync production ./build /srv/app --direction upload
```

Exit codes are stable:

| Code | Meaning |
|---:|---|
| 0 | Success |
| 2 | Command-line usage error |
| 10 | Reserved for connection failures |
| 11 | Unknown SSH host key |
| 20 | File, protocol, configuration, or transfer operation failed |
| 21 | Remote editing conflict |

Batch files contain one DebSCP command per line without the leading `debscp`.
Blank lines and `#` comments are ignored:

```text
# deploy.debscp
put production ./app.tar.gz /srv/app/app.tar.gz
sync production ./config /srv/app/config --direction upload --apply
```

Run it with `debscp batch deploy.debscp`. Execution stops at the first failure
unless `--continue-on-error` is specified.

## Python API

```python
from debscp import Client
from debscp.sync import SyncDirection

with Client("production") as client:
    for entry in client.list("/srv/app"):
        print(entry.name, entry.size)
    client.put("release.tar.gz", "/srv/app/release.tar.gz")
    checklist = client.synchronize(
        "./config", "/srv/app/config", SyncDirection.UPLOAD, apply=False
    )
```

`Client` accepts either a saved session name or a `SessionConfig` instance.
Its current stable methods are `open`, `close`, `list`, `get`, `put`, `remove`,
and `synchronize`.

