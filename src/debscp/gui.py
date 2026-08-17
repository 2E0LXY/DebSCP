from __future__ import annotations

import os
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from tkinter import messagebox, simpledialog, ttk

from .backends import SFTPBackend, UnknownHostKey
from .models import RemoteEntry, SessionConfig, normalize_remote_path
from .session_store import SessionStore
from .transfer_queue import TransferJob, TransferQueue, TransferState


class DebSCPWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("DebSCP")
        self.geometry("1120x720")
        self.minsize(820, 520)
        self.store = SessionStore()
        self.sessions = self.store.load()
        self.backend: SFTPBackend | None = None
        self.remote_entries: dict[str, RemoteEntry] = {}
        self.local_path = Path.home()
        self.remote_path = "/"
        self.queue = TransferQueue(lambda job: self.after(0, self._transfer_update, job))
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build()
        self._load_session_names()
        self._refresh_local()

    def _build(self) -> None:
        style = ttk.Style(self)
        style.configure("Treeview", rowheight=25)
        connection = ttk.LabelFrame(self, text="Connection", padding=8)
        connection.pack(fill="x", padx=10, pady=(10, 6))
        self.session_name = tk.StringVar()
        self.host = tk.StringVar()
        self.port = tk.StringVar(value="22")
        self.username = tk.StringVar(value=os.environ.get("USER", ""))
        self.password = tk.StringVar()
        self.key_file = tk.StringVar()
        fields = (
            ("Profile", self.session_name, 16), ("Host", self.host, 25),
            ("Port", self.port, 6), ("User", self.username, 15), ("Password", self.password, 16),
        )
        for index, (label, variable, width) in enumerate(fields):
            ttk.Label(connection, text=label).grid(row=0, column=index * 2, padx=(3, 2), sticky="w")
            if label == "Profile":
                self.profile_box = ttk.Combobox(connection, textvariable=variable, width=width)
                self.profile_box.bind("<<ComboboxSelected>>", self._profile_selected)
                widget = self.profile_box
            else:
                widget = ttk.Entry(connection, textvariable=variable, width=width, show="•" if label == "Password" else "")
            widget.grid(row=0, column=index * 2 + 1, padx=(0, 7), sticky="ew")
        ttk.Button(connection, text="Connect", command=self._connect).grid(row=0, column=10, padx=3)
        ttk.Button(connection, text="Save", command=self._save_profile).grid(row=0, column=11, padx=3)
        connection.columnconfigure(3, weight=1)

        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=10)
        left, right = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=1)
        self.local_path_var = tk.StringVar(value=str(self.local_path))
        self.remote_path_var = tk.StringVar(value=self.remote_path)
        self.local_tree = self._pane(left, "Local", self.local_path_var, self._local_go)
        self.remote_tree = self._pane(right, "Remote", self.remote_path_var, self._remote_go)
        self.local_tree.bind("<Double-1>", self._local_open)
        self.remote_tree.bind("<Double-1>", self._remote_open)

        actions = ttk.Frame(self, padding=(10, 7))
        actions.pack(fill="x")
        ttk.Button(actions, text="Upload →", command=self._upload).pack(side="left", padx=3)
        ttk.Button(actions, text="← Download", command=self._download).pack(side="left", padx=3)
        ttk.Button(actions, text="New remote folder", command=self._remote_mkdir).pack(side="left", padx=3)
        ttk.Button(actions, text="Rename remote", command=self._remote_rename).pack(side="left", padx=3)
        ttk.Button(actions, text="Delete remote", command=self._remote_delete).pack(side="left", padx=3)
        ttk.Button(actions, text="Refresh", command=self._refresh_all).pack(side="left", padx=3)

        queue_frame = ttk.LabelFrame(self, text="Transfers", padding=5)
        queue_frame.pack(fill="x", padx=10, pady=(0, 10))
        self.transfer_tree = ttk.Treeview(queue_frame, columns=("state", "progress"), show="headings", height=4)
        self.transfer_tree.heading("state", text="State")
        self.transfer_tree.heading("progress", text="Transfer")
        self.transfer_tree.column("state", width=100, stretch=False)
        self.transfer_tree.pack(fill="x")
        self.status = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status, anchor="w").pack(fill="x", padx=12, pady=(0, 8))

    def _pane(self, parent: ttk.Frame, title: str, path_var: tk.StringVar, go: object) -> ttk.Treeview:
        bar = ttk.Frame(parent, padding=(3, 3))
        bar.pack(fill="x")
        ttk.Label(bar, text=f"{title}:").pack(side="left")
        entry = ttk.Entry(bar, textvariable=path_var)
        entry.pack(side="left", fill="x", expand=True, padx=4)
        entry.bind("<Return>", lambda _event: go())
        ttk.Button(bar, text="Go", command=go).pack(side="right")
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=("name", "size", "modified"), show="headings", selectmode="browse")
        tree.heading("name", text="Name")
        tree.heading("size", text="Size")
        tree.heading("modified", text="Modified")
        tree.column("name", width=260)
        tree.column("size", width=90, anchor="e", stretch=False)
        tree.column("modified", width=140, stretch=False)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return tree

    def _load_session_names(self) -> None:
        self.sessions = self.store.load()
        self.profile_box["values"] = [item.name for item in self.sessions]

    def _profile_selected(self, _event: object = None) -> None:
        selected = next((item for item in self.sessions if item.name == self.session_name.get()), None)
        if selected:
            self.host.set(selected.host)
            self.port.set(str(selected.port))
            self.username.set(selected.username)
            self.key_file.set(selected.key_file or "")
            self.remote_path_var.set(selected.remote_path)

    def _config(self) -> SessionConfig:
        if not self.host.get().strip() or not self.username.get().strip():
            raise ValueError("Host and user are required")
        return SessionConfig(
            name=self.session_name.get().strip() or self.host.get().strip(),
            host=self.host.get().strip(), username=self.username.get().strip(),
            port=int(self.port.get()), key_file=self.key_file.get().strip() or None,
            remote_path=self.remote_path_var.get().strip() or "/",
        )

    def _save_profile(self) -> None:
        try:
            config = self._config()
            self.store.upsert(config)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Cannot save profile", str(exc), parent=self)
            return
        self.session_name.set(config.name)
        self._load_session_names()
        self.status.set(f"Saved {config.name}; passwords are never stored")

    def _connect(self) -> None:
        try:
            config = self._config()
        except ValueError as exc:
            messagebox.showerror("Invalid connection", str(exc), parent=self)
            return
        self.status.set(f"Connecting to {config.host}…")
        password = self.password.get() or None
        self._background(lambda: self._connect_worker(config, password))

    def _connect_worker(self, config: SessionConfig, password: str | None) -> None:
        backend = SFTPBackend(config, password)
        try:
            backend.connect()
        except UnknownHostKey as exc:
            self.after(0, self._ask_host_key, config, password, backend, exc)
            return
        if self.backend:
            self.backend.close()
        self.backend = backend
        self.remote_path = normalize_remote_path(config.remote_path)
        entries = backend.listdir(self.remote_path)
        self.after(0, self._connected, entries)

    def _ask_host_key(
        self,
        config: SessionConfig,
        password: str | None,
        backend: SFTPBackend,
        exc: UnknownHostKey,
    ) -> None:
        accepted = messagebox.askyesno(
            "Unknown SSH host key",
            f"{exc}\n\nVerify this fingerprint with the server administrator. Trust and save it?",
            icon="warning", parent=self,
        )
        if not accepted:
            self.status.set("Connection cancelled: host key was not trusted")
            return
        backend.trust_host_key(exc.hostname, exc.key)
        self.status.set("Host key saved; reconnecting…")
        self._background(lambda: self._connect_worker(config, password))

    def _connected(self, entries: list[RemoteEntry]) -> None:
        self.remote_path_var.set(self.remote_path)
        self._show_remote(entries)
        self.status.set(f"Connected to {self.host.get()} using SFTP")

    def _background(self, operation: Callable[[], object]) -> None:
        def runner() -> None:
            try:
                operation()
            except Exception as exc:  # noqa: BLE001 - UI boundary reports backend failures
                message = str(exc)
                self.after(0, lambda: messagebox.showerror("DebSCP", message, parent=self))
                self.after(0, self.status.set, "Operation failed")
        threading.Thread(target=runner, daemon=True).start()

    def _local_go(self) -> None:
        target = Path(self.local_path_var.get()).expanduser()
        if target.is_dir():
            self.local_path = target.resolve()
            self._refresh_local()
        else:
            messagebox.showerror("Local folder", f"Not a directory: {target}", parent=self)

    def _remote_go(self) -> None:
        if not self.backend:
            return
        target = normalize_remote_path(self.remote_path_var.get())
        self._background(lambda: self._remote_list_worker(target))

    def _remote_list_worker(self, target: str) -> None:
        assert self.backend
        entries = self.backend.listdir(target)
        self.remote_path = target
        self.after(0, self.remote_path_var.set, target)
        self.after(0, self._show_remote, entries)

    def _refresh_local(self) -> None:
        self.local_path_var.set(str(self.local_path))
        self.local_tree.delete(*self.local_tree.get_children())
        if self.local_path.parent != self.local_path:
            self.local_tree.insert("", "end", iid="..", values=("📁 ..", "—", ""))
        try:
            entries = sorted(self.local_path.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
        except OSError as exc:
            messagebox.showerror("Local folder", str(exc), parent=self)
            return
        for item in entries:
            try:
                details = item.stat()
                size = "—" if item.is_dir() else str(details.st_size)
                modified = __import__("datetime").datetime.fromtimestamp(details.st_mtime).strftime("%Y-%m-%d %H:%M")
            except OSError:
                size, modified = "?", "?"
            self.local_tree.insert("", "end", iid=item.name, values=(("📁 " if item.is_dir() else "") + item.name, size, modified))

    def _show_remote(self, entries: list[RemoteEntry]) -> None:
        self.remote_tree.delete(*self.remote_tree.get_children())
        self.remote_entries = {entry.name: entry for entry in entries}
        if self.remote_path != "/":
            self.remote_tree.insert("", "end", iid="..", values=("📁 ..", "—", ""))
        for entry in entries:
            self.remote_tree.insert("", "end", iid=entry.name, values=(
                ("📁 " if entry.is_dir else "") + entry.name,
                entry.display_size, entry.modified.strftime("%Y-%m-%d %H:%M"),
            ))

    def _local_open(self, _event: object) -> None:
        selected = self.local_tree.selection()
        if not selected:
            return
        name = selected[0]
        target = self.local_path.parent if name == ".." else self.local_path / name
        if target.is_dir():
            self.local_path = target.resolve()
            self._refresh_local()

    def _remote_open(self, _event: object) -> None:
        selected = self.remote_tree.selection()
        if not selected:
            return
        name = selected[0]
        if name == "..":
            self.remote_path_var.set(str(PurePosixPath(self.remote_path).parent))
            self._remote_go()
        elif self.remote_entries[name].is_dir:
            self.remote_path_var.set(self.remote_entries[name].path)
            self._remote_go()

    def _selected_local(self) -> Path | None:
        selected = self.local_tree.selection()
        return self.local_path / selected[0] if selected and selected[0] != ".." else None

    def _selected_remote(self) -> RemoteEntry | None:
        selected = self.remote_tree.selection()
        return self.remote_entries.get(selected[0]) if selected else None

    def _upload(self) -> None:
        source = self._selected_local()
        if not source or not source.is_file() or not self.backend:
            messagebox.showinfo("Upload", "Select a local file and connect first.", parent=self)
            return
        destination = str(PurePosixPath(self.remote_path, source.name))
        self.queue.submit(TransferJob(f"Upload {source.name}", lambda progress: self.backend.upload(source, destination, progress)))

    def _download(self) -> None:
        source = self._selected_remote()
        if not source or source.is_dir or not self.backend:
            messagebox.showinfo("Download", "Select a remote file and connect first.", parent=self)
            return
        destination = self.local_path / source.name
        self.queue.submit(TransferJob(f"Download {source.name}", lambda progress: self.backend.download(source.path, destination, progress)))

    def _remote_mkdir(self) -> None:
        if not self.backend:
            return
        name = simpledialog.askstring("New remote folder", "Folder name:", parent=self)
        if name and "/" not in name and name not in (".", ".."):
            path = str(PurePosixPath(self.remote_path, name))
            self._background(lambda: (self.backend.mkdir(path), self.after(0, self._refresh_remote)))

    def _remote_rename(self) -> None:
        entry = self._selected_remote()
        if not entry or not self.backend:
            return
        name = simpledialog.askstring("Rename remote item", "New name:", initialvalue=entry.name, parent=self)
        if name and "/" not in name and name not in (".", ".."):
            destination = str(PurePosixPath(self.remote_path, name))
            self._background(lambda: (self.backend.rename(entry.path, destination), self.after(0, self._refresh_remote)))

    def _remote_delete(self) -> None:
        entry = self._selected_remote()
        if not entry or not self.backend:
            return
        if messagebox.askyesno("Delete remote item", f"Permanently delete {entry.name}?", icon="warning", parent=self):
            self._background(lambda: (self.backend.remove(entry.path, directory=entry.is_dir), self.after(0, self._refresh_remote)))

    def _refresh_remote(self) -> None:
        if self.backend:
            self._remote_go()

    def _refresh_all(self) -> None:
        self._refresh_local()
        self._refresh_remote()

    def _transfer_update(self, job: TransferJob) -> None:
        progress = f"{job.transferred}/{job.total} bytes" if job.total else job.label
        if job.error:
            progress = job.error
        if self.transfer_tree.exists(job.id):
            self.transfer_tree.item(job.id, values=(job.state.value, progress))
        else:
            self.transfer_tree.insert("", 0, iid=job.id, values=(job.state.value, progress))
        if job.state == TransferState.COMPLETE:
            self._refresh_all()
        elif job.state == TransferState.FAILED:
            messagebox.showerror("Transfer failed", f"{job.label}: {job.error}", parent=self)

    def _close(self) -> None:
        self.queue.shutdown()
        if self.backend:
            self.backend.close()
        self.destroy()


def main() -> None:
    DebSCPWindow().mainloop()


if __name__ == "__main__":
    main()
