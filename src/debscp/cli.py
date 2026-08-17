from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path, PurePosixPath

from . import __version__
from .backends import SFTPBackend, UnknownHostKey
from .models import SessionConfig
from .session_store import SessionStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="debscp", description="Native Linux SFTP file manager")
    parser.add_argument("--version", action="version", version=f"DebSCP {__version__}")
    sub = parser.add_subparsers(dest="command")

    gui = sub.add_parser("gui", help="open the desktop interface")
    gui.set_defaults(command="gui")

    save = sub.add_parser("save", help="save a non-secret connection profile")
    save.add_argument("name")
    save.add_argument("host")
    save.add_argument("--user", default=getpass.getuser())
    save.add_argument("--port", type=int, default=22)
    save.add_argument("--key")
    save.add_argument("--remote-path", default="/")

    sub.add_parser("sessions", help="list saved profiles")
    for command in ("ls", "get", "put", "mkdir", "rm", "rename"):
        item = sub.add_parser(command)
        item.add_argument("session")
        item.add_argument("paths", nargs="+")
        item.add_argument("--password-stdin", action="store_true")
    return parser


def _password(args: argparse.Namespace) -> str | None:
    if getattr(args, "password_stdin", False):
        return sys.stdin.readline().rstrip("\r\n")
    return None


def _session(name: str) -> SessionConfig:
    for session in SessionStore().load():
        if session.name == name:
            return session
    raise SystemExit(f"Unknown session: {name!r}. Use 'debscp sessions' to list profiles.")


def _progress(current: int, total: int) -> None:
    percent = int(current * 100 / total) if total else 0
    print(f"\r{percent:3d}%  {current}/{total} bytes", end="", file=sys.stderr, flush=True)


def _run_remote(args: argparse.Namespace) -> int:
    config = _session(args.session)
    backend = SFTPBackend(config, _password(args))
    try:
        backend.connect()
    except UnknownHostKey as exc:
        print(exc, file=sys.stderr)
        print("Connect once with the GUI to review and trust this key.", file=sys.stderr)
        return 2
    try:
        if args.command == "ls":
            for entry in backend.listdir(args.paths[0]):
                kind = "d" if entry.is_dir else "-"
                print(f"{kind} {entry.size:>12} {entry.modified:%Y-%m-%d %H:%M} {entry.name}")
        elif args.command == "get":
            if len(args.paths) != 2:
                raise SystemExit("get requires REMOTE LOCAL")
            backend.download(args.paths[0], Path(args.paths[1]), _progress)
            print(file=sys.stderr)
        elif args.command == "put":
            if len(args.paths) != 2:
                raise SystemExit("put requires LOCAL REMOTE")
            backend.upload(Path(args.paths[0]), args.paths[1], _progress)
            print(file=sys.stderr)
        elif args.command == "mkdir":
            backend.mkdir(args.paths[0])
        elif args.command == "rm":
            entry_path = args.paths[0]
            parent = str(PurePosixPath(entry_path).parent)
            match = next((item for item in backend.listdir(parent) if item.path == entry_path), None)
            backend.remove(entry_path, directory=bool(match and match.is_dir))
        elif args.command == "rename":
            if len(args.paths) != 2:
                raise SystemExit("rename requires SOURCE DESTINATION")
            backend.rename(args.paths[0], args.paths[1])
    finally:
        backend.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.command or args.command == "gui":
        from .gui import main as gui_main

        gui_main()
        return 0
    if args.command == "sessions":
        for item in SessionStore().load():
            print(f"{item.name}\t{item.username}@{item.host}:{item.port}\t{item.remote_path}")
        return 0
    if args.command == "save":
        SessionStore().upsert(
            SessionConfig(args.name, args.host, args.user, args.port, args.key, args.remote_path)
        )
        return 0
    return _run_remote(args)


if __name__ == "__main__":
    raise SystemExit(main())

