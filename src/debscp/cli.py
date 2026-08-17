from __future__ import annotations

import argparse
import getpass
import json
import shlex
import sys
from dataclasses import asdict
from enum import IntEnum
from pathlib import Path, PurePosixPath

from . import __version__
from .backends import UnknownHostKey, create_backend
from .editor import RemoteEditConflict, RemoteEditor
from .models import SessionConfig
from .policies import PresetStore, TransferPreset
from .session_store import SessionStore
from .sync import SyncDirection, SyncEngine
from .workspaces import WorkspaceStore


class ExitCode(IntEnum):
    OK = 0
    USAGE = 2
    CONNECTION = 10
    UNKNOWN_HOST_KEY = 11
    OPERATION = 20
    CONFLICT = 21


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="debscp", description="Native Linux multi-protocol file manager")
    parser.add_argument("--version", action="version", version=f"DebSCP {__version__}")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("gui", help="open the desktop interface")

    save = sub.add_parser("save", help="save a non-secret connection profile")
    save.add_argument("name")
    save.add_argument("host", help="hostname, or S3 bucket name")
    save.add_argument("--protocol", choices=("sftp", "scp", "ftp", "ftps", "webdav", "webdavs", "s3"), default="sftp")
    save.add_argument("--user")
    save.add_argument("--port", type=int)
    save.add_argument("--key")
    save.add_argument("--remote-path", default="/")
    save.add_argument("--tls", action="store_true")
    save.add_argument("--endpoint-url")
    save.add_argument("--region")
    save.add_argument("--proxy-command")
    save.add_argument("--jump-host")

    sub.add_parser("sessions", help="list saved profiles")
    delete_session = sub.add_parser("delete-session")
    delete_session.add_argument("name")

    for command in ("ls", "get", "put", "mkdir", "rm", "rename"):
        item = sub.add_parser(command)
        item.add_argument("session")
        item.add_argument("paths", nargs="+")
        item.add_argument("--password-stdin", action="store_true")
        if command in ("get", "put", "rm"):
            item.add_argument("--recursive", action="store_true")

    sync = sub.add_parser("sync", help="compare or synchronize directory trees")
    sync.add_argument("session")
    sync.add_argument("local", type=Path)
    sync.add_argument("remote")
    sync.add_argument("--direction", choices=[item.value for item in SyncDirection], default="both")
    sync.add_argument("--delete", action="store_true")
    sync.add_argument("--apply", action="store_true", help="apply the displayed checklist")
    sync.add_argument("--watch", action="store_true", help="keep the remote tree up to date")
    sync.add_argument("--interval", type=float, default=5)
    sync.add_argument("--preset", default="Default")
    sync.add_argument("--password-stdin", action="store_true")

    edit = sub.add_parser("edit", help="edit a remote file with conflict detection")
    edit.add_argument("session")
    edit.add_argument("remote")
    edit.add_argument("--editor")
    edit.add_argument("--password-stdin", action="store_true")

    preset = sub.add_parser("preset-save", help="create or replace a transfer preset")
    preset.add_argument("name")
    preset.add_argument("--include", action="append", default=[])
    preset.add_argument("--exclude", action="append", default=[])
    sub.add_parser("presets", help="list transfer presets")

    workspace = sub.add_parser("workspace-save", help="save a group of session tabs")
    workspace.add_argument("name")
    workspace.add_argument("sessions", nargs="+")
    sub.add_parser("workspaces", help="list saved workspaces")

    batch = sub.add_parser("batch", help="execute CLI commands from a UTF-8 file or stdin")
    batch.add_argument("file", nargs="?", type=Path)
    batch.add_argument("--continue-on-error", action="store_true")

    send = sub.add_parser("send", help="Linux file-manager Send To integration")
    send.add_argument("paths", nargs="+")
    return parser


def _emit(value: object, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(value, default=str, ensure_ascii=False))
    elif isinstance(value, str):
        print(value)
    else:
        print(value)


def _password(args: argparse.Namespace) -> str | None:
    return sys.stdin.readline().rstrip("\r\n") if getattr(args, "password_stdin", False) else None


def _session(name: str) -> SessionConfig:
    try:
        return next(item for item in SessionStore().load() if item.name == name)
    except StopIteration as exc:
        raise ValueError(f"Unknown session: {name!r}. Use 'debscp sessions' to list profiles.") from exc


def _progress(current: int, total: int) -> None:
    percent = int(current * 100 / total) if total else 0
    print(f"\r{percent:3d}%  {current}/{total} bytes", end="", file=sys.stderr, flush=True)


def _remove_tree(backend, path: str) -> None:
    for entry in backend.listdir(path):
        if entry.is_dir:
            _remove_tree(backend, entry.path)
        else:
            backend.remove(entry.path)
    backend.remove(path, directory=True)


def _run_remote(args: argparse.Namespace) -> int:
    backend = create_backend(_session(args.session), _password(args))
    try:
        backend.connect()
    except UnknownHostKey as exc:
        _emit({"error": str(exc), "code": int(ExitCode.UNKNOWN_HOST_KEY)} if args.json else str(exc), json_output=args.json)
        return ExitCode.UNKNOWN_HOST_KEY
    except Exception as exc:
        raise DebSCPConnectionError(str(exc)) from exc
    try:
        if args.command == "ls":
            entries = backend.listdir(args.paths[0])
            if args.json:
                _emit([{**asdict(entry), "modified": entry.modified.isoformat()} for entry in entries], json_output=True)
            else:
                for entry in entries:
                    kind = "d" if entry.is_dir else "-"
                    print(f"{kind} {entry.size:>12} {entry.modified:%Y-%m-%d %H:%M} {entry.name}")
        elif args.command == "get":
            if len(args.paths) != 2:
                raise ValueError("get requires REMOTE LOCAL")
            operation = backend.download_tree if args.recursive else backend.download
            operation(args.paths[0], Path(args.paths[1]), None if args.json else _progress)
        elif args.command == "put":
            if len(args.paths) != 2:
                raise ValueError("put requires LOCAL REMOTE")
            operation = backend.upload_tree if args.recursive else backend.upload
            operation(Path(args.paths[0]), args.paths[1], None if args.json else _progress)
        elif args.command == "mkdir":
            backend.mkdir(args.paths[0])
        elif args.command == "rm":
            entry_path = args.paths[0]
            parent = str(PurePosixPath(entry_path).parent)
            match = next((item for item in backend.listdir(parent) if item.path == entry_path), None)
            if args.recursive and match and match.is_dir:
                _remove_tree(backend, entry_path)
            else:
                backend.remove(entry_path, directory=bool(match and match.is_dir))
        elif args.command == "rename":
            if len(args.paths) != 2:
                raise ValueError("rename requires SOURCE DESTINATION")
            backend.rename(args.paths[0], args.paths[1])
        if args.json and args.command != "ls":
            _emit({"ok": True, "command": args.command}, json_output=True)
    finally:
        backend.close()
    return ExitCode.OK


def _run_sync(args: argparse.Namespace) -> int:
    presets = {item.name: item for item in PresetStore().load()}
    if args.preset not in presets:
        raise ValueError(f"Unknown preset: {args.preset}")
    backend = create_backend(_session(args.session), _password(args))
    try:
        backend.connect()
    except UnknownHostKey:
        raise
    except Exception as exc:
        raise DebSCPConnectionError(str(exc)) from exc
    try:
        engine = SyncEngine(backend)
        if args.watch:
            engine.keep_up_to_date(args.local, args.remote, args.interval, presets[args.preset])
            return ExitCode.OK
        actions = engine.compare(args.local, args.remote, SyncDirection(args.direction), presets[args.preset], delete=args.delete)
        result = [asdict(item) for item in actions]
        text = "\n".join(f"{item.operation.value:14} {item.relative_path} — {item.reason}" for item in actions)
        _emit(result if args.json else text, json_output=args.json)
        if args.apply:
            engine.apply(actions, args.local, args.remote)
    finally:
        backend.close()
    return ExitCode.OK


def _run_batch(args: argparse.Namespace) -> int:
    content = args.file.read_text(encoding="utf-8") if args.file else sys.stdin.read()
    result = ExitCode.OK
    for number, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        code = main(shlex.split(stripped))
        if code:
            result = ExitCode(code)
            print(f"Batch line {number} failed with exit code {code}", file=sys.stderr)
            if not args.continue_on_error:
                break
    return result


def _default_port(protocol: str) -> int:
    return {"sftp": 22, "scp": 22, "ftp": 21, "ftps": 21, "webdav": 80, "webdavs": 443, "s3": 443}[protocol]


class DebSCPConnectionError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not args.command or args.command == "gui":
            from .gui import main as gui_main
            gui_main()
        elif args.command == "sessions":
            sessions = SessionStore().load()
            text = "\n".join(f"{item.name}\t{item.protocol}\t{item.username}@{item.host}:{item.port}" for item in sessions)
            _emit([item.to_dict() for item in sessions] if args.json else text, json_output=args.json)
        elif args.command == "save":
            username = args.user if args.user is not None else ("" if args.protocol == "s3" else getpass.getuser())
            SessionStore().upsert(SessionConfig(
                args.name, args.host, username, args.port or _default_port(args.protocol), args.key, args.remote_path,
                args.protocol, args.tls, args.endpoint_url, args.region, args.proxy_command, args.jump_host,
            ))
        elif args.command == "delete-session":
            SessionStore().delete(args.name)
        elif args.command in ("ls", "get", "put", "mkdir", "rm", "rename"):
            return int(_run_remote(args))
        elif args.command == "sync":
            return int(_run_sync(args))
        elif args.command == "edit":
            backend = create_backend(_session(args.session), _password(args))
            try:
                backend.connect()
            except UnknownHostKey:
                raise
            except Exception as exc:
                raise DebSCPConnectionError(str(exc)) from exc
            try:
                changed = RemoteEditor(backend).edit(args.remote, args.editor)
            finally:
                backend.close()
            _emit({"changed": changed} if args.json else ("Uploaded changes" if changed else "No changes"), json_output=args.json)
        elif args.command == "preset-save":
            store = PresetStore()
            presets = [item for item in store.load() if item.name != args.name]
            presets.append(TransferPreset(args.name, args.include or ["*"], args.exclude))
            store.save(presets)
        elif args.command == "presets":
            presets = PresetStore().load()
            _emit([asdict(item) for item in presets] if args.json else "\n".join(item.name for item in presets), json_output=args.json)
        elif args.command == "workspace-save":
            known = {item.name for item in SessionStore().load()}
            unknown = set(args.sessions) - known
            if unknown:
                raise ValueError(f"Unknown sessions: {', '.join(sorted(unknown))}")
            WorkspaceStore().set(args.name, args.sessions)
        elif args.command == "workspaces":
            workspaces = WorkspaceStore().load()
            text = "\n".join(f"{name}: {', '.join(items)}" for name, items in workspaces.items())
            _emit(workspaces if args.json else text, json_output=args.json)
        elif args.command == "batch":
            return int(_run_batch(args))
        elif args.command == "send":
            from .shell import send_files
            return send_files(args.paths)
        return int(ExitCode.OK)
    except UnknownHostKey as exc:
        _emit({"error": str(exc), "code": int(ExitCode.UNKNOWN_HOST_KEY)} if args.json else str(exc), json_output=args.json)
        return int(ExitCode.UNKNOWN_HOST_KEY)
    except DebSCPConnectionError as exc:
        _emit({"error": str(exc), "code": int(ExitCode.CONNECTION)} if args.json else str(exc), json_output=args.json)
        return int(ExitCode.CONNECTION)
    except RemoteEditConflict as exc:
        _emit({"error": str(exc), "code": int(ExitCode.CONFLICT)} if args.json else str(exc), json_output=args.json)
        return int(ExitCode.CONFLICT)
    except Exception as exc:  # noqa: BLE001 - top-level CLI boundary guarantees documented exit codes
        _emit({"error": str(exc), "code": int(ExitCode.OPERATION)} if args.json else str(exc), json_output=args.json)
        return int(ExitCode.OPERATION)


if __name__ == "__main__":
    raise SystemExit(main())
