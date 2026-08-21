from __future__ import annotations

import os
import tkinter as tk
from collections.abc import Callable
from dataclasses import replace
from tkinter import filedialog, messagebox, simpledialog, ttk

from .credentials import CredentialStore
from .models import DEFAULT_PORTS, SessionConfig
from .session_store import SessionStore
from .workspaces import WorkspaceStore


class LoginDialog(tk.Toplevel):
    """WinSCP-style saved account manager shown when DebSCP starts."""

    def __init__(
        self,
        parent: tk.Tk,
        store: SessionStore,
        credentials: CredentialStore,
        on_login: Callable[[SessionConfig, str | None], None],
        on_quick_connect: Callable[[], None],
        on_workspace: Callable[[str], None],
        on_import: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title("Connect to a site — DebSCP")
        self.geometry("820x520")
        self.minsize(720, 470)
        colors = getattr(parent, "colors", {"surface": "#202326"})
        self.configure(background=colors["surface"])
        self.attributes("-topmost", True)
        self.store = store
        self.credentials = credentials
        self.on_login = on_login
        self.on_quick_connect = on_quick_connect
        self.on_workspace = on_workspace
        self.on_import = on_import
        self.exit_on_close = str(parent.state()) == "withdrawn"
        self.sessions: dict[str, SessionConfig] = {}
        self.selected_name: str | None = None

        self.search = tk.StringVar()
        self.name = tk.StringVar()
        self.folder = tk.StringVar(value="Sites")
        self.protocol_name = tk.StringVar(value="sftp")
        self.host = tk.StringVar()
        self.port = tk.StringVar(value="22")
        self.username = tk.StringVar(value=os.environ.get("USER", ""))
        self.password = tk.StringVar()
        self.save_password = tk.BooleanVar(value=True)
        self.remote_path = tk.StringVar(value="/")
        self.key_file = tk.StringVar()
        self.proxy_command = tk.StringVar()
        self.jump_host = tk.StringVar()
        self.endpoint_url = tk.StringVar()
        self.region = tk.StringVar()
        self.status = tk.StringVar(value="Select a saved account or create a new site.")
        self._build()
        self._reload()
        self.search.trace_add("write", lambda *_args: self._populate_tree())
        self.protocol("WM_DELETE_WINDOW", self._close_application)
        self.bind("<Return>", lambda _event: self._login())
        self.after_idle(self._focus_initial)
        self.after(1200, lambda: self.attributes("-topmost", False))

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=2)
        outer.columnconfigure(1, weight=4)
        outer.rowconfigure(1, weight=1)

        saved_header = ttk.Frame(outer)
        saved_header.grid(row=0, column=0, sticky="ew", padx=(0, 12), pady=(0, 7))
        saved_header.columnconfigure(1, weight=1)
        ttk.Label(saved_header, text="SAVED ACCOUNTS", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(saved_header, text="Search", style="Muted.TLabel").grid(row=0, column=1, sticky="e", padx=(8, 5))
        ttk.Entry(saved_header, textvariable=self.search, width=15).grid(row=0, column=2, sticky="e")
        ttk.Label(outer, text="SESSION", style="Section.TLabel").grid(row=0, column=1, sticky="w", pady=(0, 7))

        tree_frame = ttk.Frame(outer)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        self.tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._tree_selected)
        self.tree.bind("<Double-1>", lambda _event: self._login())

        details = ttk.Frame(outer, style="Card.TFrame", padding=14)
        details.grid(row=1, column=1, sticky="nsew")
        details.columnconfigure(0, weight=3)
        details.columnconfigure(1, weight=2)
        ttk.Label(details, text="File protocol", style="Card.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        protocol = ttk.Combobox(
            details,
            textvariable=self.protocol_name,
            values=tuple(DEFAULT_PORTS),
            state="readonly",
        )
        protocol.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(3, 11))
        protocol.bind("<<ComboboxSelected>>", self._protocol_selected)

        def field(
            label: str,
            variable: tk.StringVar,
            row: int,
            column: int,
            *,
            show: str = "",
            browse: bool = False,
        ) -> None:
            wrapper = ttk.Frame(details, style="Card.TFrame")
            wrapper.grid(
                row=row,
                column=column,
                sticky="ew",
                padx=(0, 8) if column == 0 else (8, 0),
                pady=(0, 10),
            )
            wrapper.columnconfigure(0, weight=1)
            ttk.Label(wrapper, text=label, style="Card.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Entry(wrapper, textvariable=variable, show=show).grid(row=1, column=0, sticky="ew", pady=(3, 0))
            if browse:
                ttk.Button(wrapper, text="Browse…", command=self._choose_key).grid(
                    row=1, column=1, padx=(5, 0), pady=(3, 0)
                )

        field("Account name", self.name, 2, 0)
        field("Folder", self.folder, 2, 1)
        field("Host name", self.host, 3, 0)
        field("Port number", self.port, 3, 1)
        field("User name", self.username, 4, 0)
        field("Password", self.password, 4, 1, show="•")
        field("Remote folder", self.remote_path, 5, 0)
        field("Private key", self.key_file, 5, 1, browse=True)
        ttk.Checkbutton(details, text="Remember password securely", variable=self.save_password).grid(
            row=6, column=0, sticky="w", pady=(3, 5)
        )
        ttk.Button(details, text="Advanced…", command=self._advanced).grid(row=6, column=1, sticky="e", pady=(4, 0))

        ttk.Label(outer, textvariable=self.status, anchor="w").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(10, 7)
        )
        buttons = ttk.Frame(outer)
        buttons.grid(row=3, column=0, columnspan=2, sticky="ew")
        for text, command in (
            ("New site", self._new),
            ("Save", self._save),
            ("Duplicate", self._duplicate),
            ("Delete", self._delete),
            ("Import WinSCP…", self._import),
        ):
            ttk.Button(buttons, text=text, command=command).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Close", command=self._close_application).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="Quick Connect", command=self._quick).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="Login", command=self._login, style="Accent.TButton").pack(side="right", padx=(6, 0))

    def _focus_initial(self) -> None:
        self.lift()
        self.focus_force()
        self.tree.focus_set()

    def _reload(self, select_name: str | None = None) -> None:
        self.sessions = {item.name: item for item in self.store.load()}
        self._populate_tree(select_name)

    def _populate_tree(self, select_name: str | None = None) -> None:
        query = self.search.get().strip().casefold()
        self.tree.delete(*self.tree.get_children())
        new_id = self.tree.insert("", "end", iid="new", text="New site", open=True)
        folders: dict[str, str] = {}
        for session in sorted(self.sessions.values(), key=lambda item: (item.folder.casefold(), item.name.casefold())):
            haystack = f"{session.name} {session.host} {session.username} {session.folder}".casefold()
            if query and query not in haystack:
                continue
            folder = session.folder.strip() or "Sites"
            parent = folders.get(folder)
            if parent is None:
                parent = self.tree.insert("", "end", text=folder, open=True, tags=("folder",))
                folders[folder] = parent
            self.tree.insert(parent, "end", iid=f"session:{session.name}", text=session.name)
        workspaces = WorkspaceStore().load()
        if workspaces and not query:
            root = self.tree.insert("", "end", text="Workspaces", open=True, tags=("folder",))
            for name, members in sorted(workspaces.items()):
                self.tree.insert(root, "end", iid=f"workspace:{name}", text=f"{name}  ({len(members)} accounts)")
        target = f"session:{select_name}" if select_name in self.sessions else new_id
        if self.tree.exists(target):
            self.tree.selection_set(target)
            self.tree.focus(target)
            self.tree.see(target)

    def _tree_selected(self, _event: object = None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        item = selected[0]
        if item == "new":
            self._new(select_tree=False)
        elif item.startswith("session:"):
            self._show_session(self.sessions[item.removeprefix("session:")])
        elif item.startswith("workspace:"):
            self.status.set("Double-click or press Login to open every account in this workspace.")

    def _show_session(self, config: SessionConfig) -> None:
        self.selected_name = config.name
        self.name.set(config.name)
        self.folder.set(config.folder)
        self.protocol_name.set(config.protocol)
        self.host.set(config.host)
        self.port.set(str(config.port))
        self.username.set(config.username)
        self.password.set("")
        self.remote_path.set(config.remote_path)
        self.key_file.set(config.key_file or "")
        self.proxy_command.set(config.proxy_command or "")
        self.jump_host.set(config.jump_host or "")
        self.endpoint_url.set(config.endpoint_url or "")
        self.region.set(config.region or "")
        self.status.set(f"Selected {config.name} — {config.protocol.upper()} to {config.host}")

    def _new(self, select_tree: bool = True) -> None:
        self.selected_name = None
        self.name.set("")
        self.folder.set("Sites")
        self.protocol_name.set("sftp")
        self.host.set("")
        self.port.set("22")
        self.username.set(os.environ.get("USER", ""))
        self.password.set("")
        self.remote_path.set("/")
        self.key_file.set("")
        self.proxy_command.set("")
        self.jump_host.set("")
        self.endpoint_url.set("")
        self.region.set("")
        self.status.set("Enter the new account details, then Save or Login.")
        if select_tree and self.tree.exists("new"):
            self.tree.selection_set("new")

    def _config(self) -> SessionConfig:
        host = self.host.get().strip()
        protocol = self.protocol_name.get()
        username = self.username.get().strip()
        if not host:
            raise ValueError("Host name or S3 bucket is required")
        if protocol != "s3" and not username:
            raise ValueError("User name is required")
        try:
            port = int(self.port.get())
        except ValueError as exc:
            raise ValueError("Port must be a number") from exc
        if not 1 <= port <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        name = self.name.get().strip() or host
        return SessionConfig(
            name=name,
            host=host,
            username=username,
            port=port,
            key_file=self.key_file.get().strip() or None,
            remote_path=self.remote_path.get().strip() or "/",
            protocol=protocol,
            tls=protocol in {"ftps", "ftps-implicit", "webdavs"},
            endpoint_url=self.endpoint_url.get().strip() or None,
            region=self.region.get().strip() or None,
            proxy_command=self.proxy_command.get().strip() or None,
            jump_host=self.jump_host.get().strip() or None,
            folder=self.folder.get().strip() or "Sites",
        )

    def _save(self) -> SessionConfig | None:
        try:
            config = self._config()
            old_name = self.selected_name
            if config.name != old_name and config.name in self.sessions:
                raise ValueError(f"An account named {config.name!r} already exists")
            if old_name:
                self.store.replace(old_name, config)
            else:
                self.store.upsert(config)
            secret = self.password.get()
            if self.save_password.get() and secret:
                self.credentials.set(config.name, secret)
            if old_name and old_name != config.name:
                old_secret = self.credentials.get(old_name)
                if old_secret and not secret:
                    self.credentials.set(config.name, old_secret)
                self.credentials.delete(old_name)
            self.selected_name = config.name
            self._reload(config.name)
            self.status.set(f"Saved {config.name}; secrets are kept in the system credential store.")
            return config
        except (OSError, RuntimeError, ValueError) as exc:
            messagebox.showerror("Cannot save account", str(exc), parent=self)
            return None

    def _login(self) -> None:
        selected = self.tree.selection()
        if selected and selected[0].startswith("workspace:"):
            name = selected[0].removeprefix("workspace:")
            self.destroy()
            self.on_workspace(name)
            return
        try:
            config = self._config()
            password = self.password.get() or self.credentials.get(config.name)
            if self.selected_name and self.save_password.get() and self.password.get():
                self.credentials.set(config.name, self.password.get())
        except (RuntimeError, ValueError) as exc:
            messagebox.showerror("Cannot log in", str(exc), parent=self)
            return
        self.destroy()
        self.on_login(config, password)

    def _duplicate(self) -> None:
        try:
            original = self._config()
        except ValueError as exc:
            messagebox.showerror("Cannot duplicate account", str(exc), parent=self)
            return
        number = 2
        name = f"{original.name} copy"
        while name in self.sessions:
            name = f"{original.name} copy {number}"
            number += 1
        duplicate = replace(original, name=name)
        self.store.upsert(duplicate)
        self._reload(name)

    def _delete(self) -> None:
        if not self.selected_name:
            return
        name = self.selected_name
        if not messagebox.askyesno("Delete account", f"Delete the saved account {name!r}?", parent=self):
            return
        self.store.delete(name)
        self.credentials.delete(name)
        self._new(select_tree=False)
        self._reload()

    def _protocol_selected(self, _event: object = None) -> None:
        self.port.set(str(DEFAULT_PORTS[self.protocol_name.get()]))

    def _choose_key(self) -> None:
        selected = filedialog.askopenfilename(title="Select private key", parent=self)
        if selected:
            self.key_file.set(selected)

    def _advanced(self) -> None:
        fields = (
            ("Jump host (user@host)", self.jump_host),
            ("Proxy command", self.proxy_command),
            ("S3 endpoint URL", self.endpoint_url),
            ("S3 region", self.region),
        )
        for label, variable in fields:
            value = simpledialog.askstring(
                "Advanced account settings", f"{label}:", initialvalue=variable.get(), parent=self
            )
            if value is None:
                break
            variable.set(value.strip())

    def _import(self) -> None:
        self.on_import()
        self._reload()

    def _quick(self) -> None:
        self.destroy()
        self.on_quick_connect()

    def _close_application(self) -> None:
        if self.exit_on_close:
            self.master.destroy()
        else:
            self.destroy()
