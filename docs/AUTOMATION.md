# Automation reference

## CLI contract

Use `--json` before the subcommand for machine-readable results:

```sh
debscp --json sessions
debscp --json ls production /srv/app
debscp --json sync production ./build /srv/app --direction upload
debscp --json import-ini ~/Backups/WinSCP.ini
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

`import-ini FILE` imports all usable saved sites from a WinSCP configuration
backup. Its JSON result contains `imported`, `passwords_imported`, `profiles`,
`renamed`, and `warnings`. Name collisions are renamed by default; pass
`--overwrite` to replace existing profiles. Standard WinSCP passwords are
decrypted into the system credential store and never emitted in JSON.

## Python API

```python
from debscp import Client
from debscp.sync import SyncDirection

with Client("production") as client:
    for entry in client.list("/srv/app"):
        print(entry.name, entry.size)
    client.put("release.tar.gz", "/srv/app/release.tar.gz")
    checklist = client.synchronize("./config", "/srv/app/config", SyncDirection.UPLOAD, apply=False)
```

`Client` accepts either a saved session name or a `SessionConfig` instance.
Its stable methods are `open`, `close`, `list`, `get`, `put`, `remove`,
`remove_tree`, `mkdir`, `rename`, `edit`, `synchronize`, and `keep_up_to_date`.
The `capabilities` property reports protocol-specific transfer behavior.
