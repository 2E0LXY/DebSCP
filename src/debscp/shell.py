from __future__ import annotations

import tkinter as tk
from pathlib import Path, PurePosixPath
from tkinter import messagebox, simpledialog

from .backends import create_backend
from .credentials import CredentialStore
from .session_store import SessionStore


def send_files(paths: list[str]) -> int:
    files = [Path(item) for item in paths]
    if not files or any(not item.exists() for item in files):
        raise ValueError("Select one or more existing files")
    sessions = SessionStore().load()
    if not sessions:
        raise ValueError("Create a saved DebSCP session first")
    root = tk.Tk()
    root.withdraw()
    names = "\n".join(f"• {item.name} ({item.protocol})" for item in sessions)
    name = simpledialog.askstring("Send with DebSCP", f"Saved sessions:\n{names}\n\nSession name:", parent=root)
    if not name:
        root.destroy()
        return 1
    session = next((item for item in sessions if item.name == name), None)
    if not session:
        messagebox.showerror("DebSCP", f"Unknown session: {name}", parent=root)
        root.destroy()
        return 2
    password = CredentialStore().get(session.name)
    if password is None:
        password = simpledialog.askstring("DebSCP", "Password (leave empty for key/agent):", show="•", parent=root)
    backend = create_backend(session, password or None)
    try:
        backend.connect()
        for item in files:
            destination = str(PurePosixPath(session.remote_path, item.name))
            if item.is_dir():
                backend.upload_tree(item, destination)
            else:
                backend.upload(item, destination)
    finally:
        backend.close()
        root.destroy()
    return 0


def main() -> int:
    import sys

    return send_files(sys.argv[1:])
