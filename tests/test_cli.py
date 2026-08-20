import json

from debscp.cli import ExitCode, main


def test_cli_json_session_round_trip(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert main(["save", "site", "example.test", "--protocol", "webdavs", "--user", "alex"]) == ExitCode.OK
    assert main(["--json", "sessions"]) == ExitCode.OK
    value = json.loads(capsys.readouterr().out)
    assert value[0]["protocol"] == "webdavs"
    assert value[0]["port"] == 443


def test_cli_returns_stable_operation_error(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert main(["--json", "ls", "missing", "/"]) == ExitCode.OPERATION
    assert json.loads(capsys.readouterr().out)["code"] == 20


def test_batch_executes_multiple_commands(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    batch = tmp_path / "commands.debscp"
    batch.write_text("save one host.test --user user\nsave two bucket --protocol s3\n")
    assert main(["batch", str(batch)]) == ExitCode.OK
    assert main(["workspace-save", "pair", "one", "two"]) == ExitCode.OK


def test_cli_imports_winscp_backup_as_json(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    backup = tmp_path / "WinSCP.ini"
    backup.write_text("[Sessions\\Production%20SFTP]\nHostName=prod.test\nUserName=alex\nFSProtocol=2\n")
    assert main(["--json", "import-ini", str(backup)]) == ExitCode.OK
    report = json.loads(capsys.readouterr().out)
    assert report["profiles"] == ["Production SFTP"]
    assert report["warnings"] == []
    assert main(["--json", "sessions"]) == ExitCode.OK
    assert json.loads(capsys.readouterr().out)[0]["host"] == "prod.test"


def test_cli_import_stores_password_outside_profile_json(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    saved: dict[str, str] = {}

    class FakeCredentialStore:
        def set(self, name: str, password: str) -> None:
            saved[name] = password

    monkeypatch.setattr("debscp.cli.CredentialStore", FakeCredentialStore)
    backup = tmp_path / "WinSCP.ini"
    backup.write_text("[Sessions\\Site]\nHostName=host.test\nUserName=alex\nPasswordPlain=top-secret\n")
    assert main(["--json", "import-ini", str(backup)]) == ExitCode.OK
    output = capsys.readouterr().out
    assert json.loads(output)["passwords_imported"] == 1
    assert "top-secret" not in output
    assert saved == {"Site": "top-secret"}
    assert "top-secret" not in (tmp_path / "config" / "debscp" / "sessions.json").read_text()
