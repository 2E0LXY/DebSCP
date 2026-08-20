from __future__ import annotations

import os
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path, PurePosixPath
from tkinter import filedialog, messagebox, simpledialog, ttk

from .backends import RemoteBackend, SFTPBackend, UnknownHostKey, create_backend
from .credentials import CredentialStore
from .editor import RemoteEditConflict, RemoteEditor
from .i18n import _
from .models import DEFAULT_PORTS, RemoteEntry, SessionConfig, normalize_remote_path
from .session_store import SessionStore
from .sync import SyncDirection, SyncEngine
from .transfer_queue import TransferJob, TransferQueue, TransferState
from .winscp_ini import load_winscp_ini
from .workspaces import WorkspaceStore


class DebSCPWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("DebSCP")
        self.geometry("1120x720")
        self.minsize(820, 520)
        self.store = SessionStore()
        self.credential_store = CredentialStore()
        self.sessions = self.store.load()
        self.backend: RemoteBackend | None = None
        self.connections: dict[str, tuple[RemoteBackend, str]] = {}
        self.tab_names: dict[str, str] = {}
        self.active_session: str | None = None
        self.remote_entries: dict[str, RemoteEntry] = {}
        self.local_path = Path.home()
        self.remote_path = "/"
        self.closing = False
        self._background_threads: set[threading.Thread] = set()
        self._background_lock = threading.Lock()
        self.queue = TransferQueue(self._queue_update)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build()
        self._load_session_names()
        self._refresh_local()

    def _build(self) -> None:
        style = ttk.Style(self)
        style.configure("Treeview", rowheight=25)
        connection = ttk.LabelFrame(self, text=_("Connection"), padding=8)
        connection.pack(fill="x", padx=10, pady=(10, 6))
        self.session_name = tk.StringVar()
        self.protocol_name = tk.StringVar(value="sftp")
        self.host = tk.StringVar()
        self.port = tk.StringVar(value="22")
        self.username = tk.StringVar(value=os.environ.get("USER", ""))
        self.password = tk.StringVar()
        self.key_file = tk.StringVar()
        fields = (
            ("Profile", self.session_name, 16),
            ("Host", self.host, 25),
            ("Port", self.port, 6),
            ("User", self.username, 15),
            ("Password", self.password, 16),
        )
        for index, (label, variable, width) in enumerate(fields):
            ttk.Label(connection, text=label).grid(row=0, column=index * 2, padx=(3, 2), sticky="w")
            if label == "Profile":
                self.profile_box = ttk.Combobox(connection, textvariable=variable, width=width)
                self.profile_box.bind("<<ComboboxSelected>>", self._profile_selected)
                self.profile_box.grid(row=0, column=index * 2 + 1, padx=(0, 7), sticky="ew")
            else:
                widget = ttk.Entry(
                    connection, textvariable=variable, width=width, show="•" if label == "Password" else ""
                )
                widget.grid(row=0, column=index * 2 + 1, padx=(0, 7), sticky="ew")
        ttk.Button(connection, text=_("Connect"), command=self._connect).grid(row=0, column=10, padx=3)
        ttk.Button(connection, text=_("Save"), command=self._save_profile).grid(row=0, column=11, padx=3)
        ttk.Label(connection, text="Protocol").grid(row=1, column=0, padx=(3, 2), pady=(6, 0), sticky="w")
        protocol_box = ttk.Combobox(
            connection,
            textvariable=self.protocol_name,
            values=("sftp", "scp", "ftp", "ftps", "ftps-implicit", "webdav", "webdavs", "s3"),
            state="readonly",
            width=13,
        )
        protocol_box.grid(row=1, column=1, padx=(0, 7), pady=(6, 0), sticky="w")
        protocol_box.bind("<<ComboboxSelected>>", self._protocol_selected)
        ttk.Label(
            connection, text="Advanced proxy, endpoint, region, and key options are loaded from saved profiles"
        ).grid(
            row=1,
            column=2,
            columnspan=7,
            pady=(6, 0),
            sticky="w",
        )
        ttk.Button(connection, text="Import WinSCP INI", command=self._import_winscp_ini).grid(
            row=1, column=9, padx=3, pady=(6, 0)
        )
        ttk.Button(connection, text="Save workspace", command=self._save_workspace).grid(
            row=1, column=10, padx=3, pady=(6, 0)
        )
        ttk.Button(connection, text="Open workspace", command=self._open_workspace).grid(
            row=1, column=11, padx=3, pady=(6, 0)
        )
        connection.columnconfigure(3, weight=1)

        self.tabs = ttk.Notebook(self, height=28)
        self.tabs.pack(fill="x", padx=10, pady=(0, 6))
        self.tabs.bind("<<NotebookTabChanged>>", self._tab_changed)

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
        ttk.Button(actions, text=_("Upload") + " →", command=self._upload).pack(side="left", padx=3)
        ttk.Button(actions, text="← " + _("Download"), command=self._download).pack(side="left", padx=3)
        ttk.Button(actions, text="New remote folder", command=self._remote_mkdir).pack(side="left", padx=3)
        ttk.Button(actions, text="Rename remote", command=self._remote_rename).pack(side="left", padx=3)
        ttk.Button(actions, text="Delete remote", command=self._remote_delete).pack(side="left", padx=3)
        ttk.Button(actions, text="Edit remote", command=self._remote_edit).pack(side="left", padx=3)
        ttk.Button(actions, text="Sync…", command=self._sync).pack(side="left", padx=3)
        ttk.Button(actions, text="Close tab", command=self._close_tab).pack(side="left", padx=3)
        ttk.Button(actions, text=_("Refresh"), command=self._refresh_all).pack(side="left", padx=3)

        queue_frame = ttk.LabelFrame(self, text=_("Transfers"), padding=5)
        queue_frame.pack(fill="x", padx=10, pady=(0, 10))
        self.transfer_tree = ttk.Treeview(queue_frame, columns=("state", "progress"), show="headings", height=4)
        self.transfer_tree.heading("state", text="State")
        self.transfer_tree.heading("progress", text="Transfer")
        self.transfer_tree.column("state", width=100, stretch=False)
        self.transfer_tree.pack(fill="x")
        self.status = tk.StringVar(value=_("Ready"))
        ttk.Label(self, textvariable=self.status, anchor="w").pack(fill="x", padx=12, pady=(0, 8))

    def _pane(
        self,
        parent: ttk.Frame,
        title: str,
        path_var: tk.StringVar,
        go: Callable[[], object],
    ) -> ttk.Treeview:
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
            self.password.set("")
            self.host.set(selected.host)
            self.port.set(str(selected.port))
            self.username.set(selected.username)
            self.protocol_name.set(selected.protocol)
            self.key_file.set(selected.key_file or "")
            self.remote_path_var.set(selected.remote_path)

    def _protocol_selected(self, _event: object = None) -> None:
        self.port.set(str(DEFAULT_PORTS[self.protocol_name.get()]))

    def _config(self) -> SessionConfig:
        if not self.host.get().strip():
            raise ValueError("Host or bucket is required")
        if self.protocol_name.get() != "s3" and not self.username.get().strip():
            raise ValueError("User is required for this protocol")
        name = self.session_name.get().strip() or self.host.get().strip()
        protocol = self.protocol_name.get()
        host, username = self.host.get().strip(), self.username.get().strip()
        port, key_file = int(self.port.get()), self.key_file.get().strip() or None
        remote_path, tls = (
            self.remote_path_var.get().strip() or "/",
            protocol
            in (
                "ftps",
                "ftps-implicit",
                "webdavs",
            ),
        )
        existing = next((item for item in self.sessions if item.name == name), None)
        if existing:
            return replace(
                existing,
                name=name,
                host=host,
                username=username,
                port=port,
                key_file=key_file,
                remote_path=remote_path,
                protocol=protocol,
                tls=tls,
            )
        return SessionConfig(name, host, username, port, key_file, remote_path, protocol, tls)

    def _save_profile(self) -> None:
        try:
            config = self._config()
            self.store.upsert(config)
            if self.password.get():
                self.credential_store.set(config.name, self.password.get())
        except (OSError, RuntimeError, ValueError) as exc:
            messagebox.showerror("Cannot save profile", str(exc), parent=self)
            return
        self.session_name.set(config.name)
        self._load_session_names()
        self.status.set(f"Saved {config.name}; password is protected by the system credential store")

    def _import_winscp_ini(self) -> None:
        selected = filedialog.askopenfilename(
            title="Import WinSCP backup",
            filetypes=(("WinSCP INI backup", "*.ini"), ("All files", "*")),
            parent=self,
        )
        if not selected:
            return
        try:
            result = load_winscp_ini(Path(selected))
            if not result.sessions:
                raise ValueError("The backup contains no importable WinSCP sites")
            stored, renamed = self.store.merge(list(result.sessions))
            credential_by_name = {item.session_name: item.password for item in result.credentials}
            passwords_imported = 0
            for source, stored_name in zip(result.sessions, stored, strict=True):
                password = credential_by_name.get(source.name)
                if password:
                    self.credential_store.set(stored_name, password)
                    passwords_imported += 1
        except (OSError, RuntimeError, ValueError) as exc:
            messagebox.showerror("Cannot import WinSCP backup", str(exc), parent=self)
            return
        self._load_session_names()
        details = [f"Imported {len(stored)} site(s) and {passwords_imported} password(s)."]
        if renamed:
            details.append("Name collisions were kept as: " + ", ".join(renamed))
        if result.warnings:
            details.append("\nWarnings:\n" + "\n".join(f"• {item}" for item in result.warnings))
        messagebox.showinfo("WinSCP import complete", "\n".join(details), parent=self)
        self.status.set(f"Imported {len(stored)} WinSCP site(s) and {passwords_imported} password(s)")

    def _connect(self) -> None:
        try:
            config = self._config()
            password = self.password.get() or self.credential_store.get(config.name)
        except (RuntimeError, ValueError) as exc:
            messagebox.showerror("Invalid connection", str(exc), parent=self)
            return
        if config.protocol == "ftp" and not messagebox.askyesno(
            "Unencrypted FTP",
            "FTP sends credentials and file data without encryption. Continue anyway?\n\nUse FTPS or SFTP when possible.",
            icon="warning",
            parent=self,
        ):
            return
        self.status.set(f"Connecting to {config.host}…")
        self._background(lambda: self._connect_worker(config, password))

    def _connect_worker(self, config: SessionConfig, password: str | None) -> None:
        backend = create_backend(config, password)
        try:
            backend.connect()
        except UnknownHostKey as exc:
            if not isinstance(backend, SFTPBackend):
                raise
            self.after(0, self._ask_host_key, config, password, backend, exc)
            return
        remote_path = normalize_remote_path(config.remote_path)
        entries = backend.listdir(remote_path)
        self.after(0, self._connected, config.name, backend, remote_path, entries)

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
            icon="warning",
            parent=self,
        )
        if not accepted:
            self.status.set("Connection cancelled: host key was not trusted")
            return
        backend.trust_host_key(exc.hostname, exc.key)
        self.status.set("Host key saved; reconnecting…")
        self._background(lambda: self._connect_worker(config, password))

    def _connected(self, name: str, backend: RemoteBackend, remote_path: str, entries: list[RemoteEntry]) -> None:
        old = self.connections.get(name)
        if old and old[0] is not backend:
            old[0].close()
        self.backend = backend
        self.remote_path = remote_path
        self.connections[name] = (backend, remote_path)
        if name not in self.tab_names.values():
            frame = ttk.Frame(self.tabs)
            self.tabs.add(frame, text=name)
            self.tab_names[str(frame)] = name
        for tab_id, tab_name in self.tab_names.items():
            if tab_name == name:
                self.tabs.select(tab_id)
                break
        self.active_session = name
        self.remote_path_var.set(self.remote_path)
        self._show_remote(entries)
        self.status.set(f"Connected to {self.host.get()} using {self.protocol_name.get().upper()}")

    def _background(self, operation: Callable[[], object]) -> None:
        if self.closing:
            return

        def runner() -> None:
            try:
                operation()
            except Exception as exc:  # noqa: BLE001 - UI boundary reports backend failures
                message = str(exc)
                if not self.closing:
                    self.after(0, lambda: messagebox.showerror("DebSCP", message, parent=self))
                    self.after(0, self.status.set, "Operation failed")
            finally:
                with self._background_lock:
                    self._background_threads.discard(threading.current_thread())

        worker = threading.Thread(target=runner, daemon=True)
        with self._background_lock:
            self._background_threads.add(worker)
        worker.start()

    def _queue_update(self, job: TransferJob) -> None:
        if not self.closing:
            self.after(0, self._transfer_update, job)

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
        backend, session = self.backend, self.active_session
        self._background(lambda: self._remote_list_worker(backend, session, target))

    def _remote_list_worker(self, backend: RemoteBackend, session: str | None, target: str) -> None:
        entries = backend.listdir(target)
        if backend is not self.backend or session != self.active_session:
            return
        self.remote_path = target
        if session:
            self.connections[session] = (backend, target)
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
            self.local_tree.insert(
                "", "end", iid=item.name, values=(("📁 " if item.is_dir() else "") + item.name, size, modified)
            )

    def _show_remote(self, entries: list[RemoteEntry]) -> None:
        self.remote_tree.delete(*self.remote_tree.get_children())
        self.remote_entries = {entry.name: entry for entry in entries}
        if self.remote_path != "/":
            self.remote_tree.insert("", "end", iid="..", values=("📁 ..", "—", ""))
        for entry in entries:
            self.remote_tree.insert(
                "",
                "end",
                iid=entry.name,
                values=(
                    ("📁 " if entry.is_dir else "") + entry.name,
                    entry.display_size,
                    entry.modified.strftime("%Y-%m-%d %H:%M"),
                ),
            )

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
        if not source or not source.exists() or not self.backend:
            messagebox.showinfo("Upload", "Select a local item and connect first.", parent=self)
            return
        destination = str(PurePosixPath(self.remote_path, source.name))
        backend = self.backend
        operation = backend.upload_tree if source.is_dir() else backend.upload
        self.queue.submit(
            TransferJob(f"Upload {source.name}", lambda progress: operation(source, destination, progress))
        )

    def _download(self) -> None:
        source = self._selected_remote()
        if not source or not self.backend:
            messagebox.showinfo("Download", "Select a remote item and connect first.", parent=self)
            return
        destination = self.local_path / source.name
        backend = self.backend
        operation = backend.download_tree if source.is_dir else backend.download
        self.queue.submit(
            TransferJob(f"Download {source.name}", lambda progress: operation(source.path, destination, progress)),
        )

    def _remote_mkdir(self) -> None:
        if not self.backend:
            return
        name = simpledialog.askstring("New remote folder", "Folder name:", parent=self)
        if name and "/" not in name and name not in (".", ".."):
            path = str(PurePosixPath(self.remote_path, name))
            backend = self.backend
            self._background(lambda: (backend.mkdir(path), self.after(0, self._refresh_backend, backend)))

    def _remote_rename(self) -> None:
        entry = self._selected_remote()
        if not entry or not self.backend:
            return
        name = simpledialog.askstring("Rename remote item", "New name:", initialvalue=entry.name, parent=self)
        if name and "/" not in name and name not in (".", ".."):
            destination = str(PurePosixPath(self.remote_path, name))
            backend = self.backend
            self._background(
                lambda: (backend.rename(entry.path, destination), self.after(0, self._refresh_backend, backend))
            )

    def _remote_delete(self) -> None:
        entry = self._selected_remote()
        if not entry or not self.backend:
            return
        if messagebox.askyesno("Delete remote item", f"Permanently delete {entry.name}?", icon="warning", parent=self):
            backend = self.backend

            def remove() -> None:
                if entry.is_dir:
                    backend.remove_tree(entry.path)
                else:
                    backend.remove(entry.path)
                self.after(0, self._refresh_backend, backend)

            self._background(remove)

    def _refresh_backend(self, backend: RemoteBackend) -> None:
        if backend is self.backend:
            self._refresh_remote()

    def _refresh_remote(self) -> None:
        if self.backend:
            self._remote_go()

    def _refresh_all(self) -> None:
        self._refresh_local()
        self._refresh_remote()

    def _tab_changed(self, _event: object = None) -> None:
        selected = self.tabs.select()
        name = self.tab_names.get(selected)
        if not name or name == self.active_session or name not in self.connections:
            return
        self.active_session = name
        self.backend, self.remote_path = self.connections[name]
        session = next((item for item in self.sessions if item.name == name), None)
        if session:
            self.session_name.set(session.name)
            self.host.set(session.host)
            self.port.set(str(session.port))
            self.username.set(session.username)
            self.protocol_name.set(session.protocol)
        self.remote_path_var.set(self.remote_path)
        self._remote_go()

    def _close_tab(self) -> None:
        with self._background_lock:
            background_active = bool(self._background_threads)
        if self.queue.active or background_active:
            messagebox.showinfo(
                "Connection busy", "Wait for active transfers and remote operations before closing a tab.", parent=self
            )
            return
        selected = self.tabs.select()
        name = self.tab_names.pop(selected, None)
        if not name:
            return
        backend, _path = self.connections.pop(name)
        backend.close()
        self.tabs.forget(selected)
        self.active_session = None
        self.backend = None
        self.remote_tree.delete(*self.remote_tree.get_children())
        if self.tabs.tabs():
            self.tabs.select(self.tabs.tabs()[0])
            self._tab_changed()

    def _save_workspace(self) -> None:
        if not self.connections:
            messagebox.showinfo("Workspace", "Connect at least one session first.", parent=self)
            return
        name = simpledialog.askstring("Save workspace", "Workspace name:", parent=self)
        if name:
            WorkspaceStore().set(name, list(self.connections))
            self.status.set(f"Saved workspace {name}")

    def _open_workspace(self) -> None:
        workspaces = WorkspaceStore().load()
        if not workspaces:
            messagebox.showinfo("Workspace", "No saved workspaces.", parent=self)
            return
        listing = "\n".join(f"• {name}: {', '.join(sessions)}" for name, sessions in workspaces.items())
        name = simpledialog.askstring("Open workspace", f"{listing}\n\nWorkspace name:", parent=self)
        if not name or name not in workspaces:
            return
        saved = {item.name: item for item in self.sessions}
        for session_name in workspaces[name]:
            config = saved.get(session_name)
            if config and session_name not in self.connections:
                password = self.credential_store.get(session_name)
                if config.protocol != "s3" and password is None:
                    password = simpledialog.askstring(
                        "Workspace credentials",
                        f"Password for {session_name} (blank for key/agent):",
                        show="•",
                        parent=self,
                    )
                    if password is None:
                        continue
                    password = password or None

                def connect(selected: SessionConfig = config, secret: str | None = password) -> None:
                    self._connect_worker(selected, secret)

                self._background(connect)

    def _remote_edit(self) -> None:
        entry = self._selected_remote()
        if not entry or entry.is_dir or not self.backend:
            messagebox.showinfo("Remote edit", "Select a remote file first.", parent=self)
            return
        editor = simpledialog.askstring(
            "Remote edit",
            "Editor command (must wait until the editor closes):",
            initialvalue=os.environ.get("VISUAL") or os.environ.get("EDITOR") or "gedit --standalone",
            parent=self,
        )
        if not editor:
            return
        backend = self.backend

        def edit() -> None:
            try:
                changed = RemoteEditor(backend).edit(entry.path, editor)
            except RemoteEditConflict as exc:
                message = str(exc)
                self.after(0, lambda: messagebox.showerror("Edit conflict", message, parent=self))
                return
            self.after(0, self.status.set, "Uploaded edited file" if changed else "Remote file was unchanged")
            self.after(0, self._refresh_remote)

        self._background(edit)

    def _sync(self) -> None:
        if not self.backend:
            return
        remote = simpledialog.askstring("Synchronize", "Remote directory:", initialvalue=self.remote_path, parent=self)
        if not remote:
            return
        direction = simpledialog.askstring(
            "Synchronize", "Direction: upload, download, or both", initialvalue="both", parent=self
        )
        if direction not in {item.value for item in SyncDirection}:
            messagebox.showerror("Synchronize", "Direction must be upload, download, or both.", parent=self)
            return
        backend = self.backend
        local = self.local_path

        def compare() -> None:
            engine = SyncEngine(backend)
            actions = engine.compare(local, remote, SyncDirection(direction))
            summary = "\n".join(f"{item.operation.value}: {item.relative_path}" for item in actions[:50])
            if len(actions) > 50:
                summary += f"\n…and {len(actions) - 50} more"
            self.after(0, self._confirm_sync, engine, actions, local, remote, summary)

        self._background(compare)

    def _confirm_sync(self, engine: SyncEngine, actions: list, local: Path, remote: str, summary: str) -> None:
        if not actions:
            messagebox.showinfo("Synchronize", "Directories are already synchronized.", parent=self)
            return
        if messagebox.askyesno("Synchronize checklist", f"{summary}\n\nApply these operations?", parent=self):

            def apply_sync() -> None:
                engine.apply(actions, local, remote)
                self.after(0, self._refresh_all)

            self._background(apply_sync)

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
        if self.closing:
            return
        self.closing = True
        self.status.set("Waiting for active transfers to finish…")
        self.update_idletasks()

        def wait_for_workers() -> None:
            self.queue.shutdown()
            while True:
                with self._background_lock:
                    background_threads = list(self._background_threads)
                if not background_threads:
                    break
                for worker in background_threads:
                    worker.join()
            self.after(0, self._finish_close)

        threading.Thread(target=wait_for_workers, name="debscp-shutdown", daemon=True).start()

    def _finish_close(self) -> None:
        for backend, _path in list(self.connections.values()):
            backend.close()
        self.connections.clear()
        self.destroy()


def main() -> None:
    DebSCPWindow().mainloop()


if __name__ == "__main__":
    main()
