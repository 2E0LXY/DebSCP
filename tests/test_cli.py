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
