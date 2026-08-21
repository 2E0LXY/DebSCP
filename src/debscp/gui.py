from __future__ import annotations

import os
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import __version__
from .backends import RemoteBackend, SFTPBackend, UnknownHostKey, create_backend
from .credentials import CredentialStore
from .editor import RemoteEditConflict, RemoteEditor
from .i18n import _
from .login_dialog import LoginDialog
from .models import DEFAULT_PORTS, RemoteEntry, SessionConfig, normalize_remote_path
from .session_store import SessionStore
from .sync import SyncDirection, SyncEngine
from .transfer_queue import TransferJob, TransferQueue, TransferState
from .updater import (
    UpdateInfo,
    check_for_update,
    download_update,
    launch_installer_after_exit,
    verify_debian_package,
)
from .winscp_ini import load_winscp_ini
from .workspaces import WorkspaceStore


def display_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def local_type(path: Path) -> str:
    if path.is_dir():
        return "File folder"
    suffix = path.suffix.removeprefix(".").upper()
    return f"{suffix} file" if suffix else "File"


class DebSCPWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("DebSCP")
        self.geometry("1180x760")
        self.minsize(900, 580)
        self.ui_font = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
        self.colors = {
            "window": "#17191b",
            "surface": "#202326",
            "panel": "#181a1c",
            "panel_alt": "#25282b",
            "border": "#3a3e42",
            "text": "#f2f4f5",
            "muted": "#a8afb5",
            "accent": "#157fd1",
            "accent_hover": "#2997e8",
            "warning": "#f0a229",
        }
        self.configure(background=self.colors["window"])
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
        self.available_update: UpdateInfo | None = None
        self._update_checking = False
        self._update_flash_on = False
        self._update_flash_running = False
        self._update_helper: object | None = None
        self._next_update_check: str | None = None
        self._background_threads: set[threading.Thread] = set()
        self._background_lock = threading.Lock()
        self.queue = TransferQueue(self._queue_update)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build()
        self._load_session_names()
        self._refresh_local()
        self._next_update_check = self.after(1500, self._check_for_updates)
        self.withdraw()
        self.after_idle(self._show_login_dialog)

    def _build(self) -> None:
        self._configure_theme()
        self.session_name = tk.StringVar()
        self.protocol_name = tk.StringVar(value="sftp")
        self.host = tk.StringVar()
        self.port = tk.StringVar(value="22")
        self.username = tk.StringVar(value=os.environ.get("USER", ""))
        self.password = tk.StringVar()
        self.key_file = tk.StringVar()
        self.local_path_var = tk.StringVar(value=str(self.local_path))
        self.remote_path_var = tk.StringVar(value=self.remote_path)

        self._build_menu()
        toolbar = ttk.Frame(self, style="Toolbar.TFrame", padding=(6, 5))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="New session", style="Toolbar.TButton", command=self._show_login_dialog).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(toolbar, text="Synchronize", style="Toolbar.TButton", command=self._sync).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Transfer queue", style="Toolbar.TButton", command=self._toggle_queue).pack(
            side="left", padx=4
        )
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=7)
        ttk.Label(toolbar, text="Saved site", style="Toolbar.TLabel").pack(side="left", padx=(0, 5))
        self.profile_box = ttk.Combobox(toolbar, textvariable=self.session_name, state="readonly", width=23)
        self.profile_box.bind("<<ComboboxSelected>>", self._profile_selected)
        self.profile_box.pack(side="left")
        ttk.Button(toolbar, text="Connect", style="Accent.TButton", command=self._connect).pack(side="left", padx=5)
        ttk.Label(toolbar, text="Transfer preset", style="Toolbar.TLabel").pack(side="left", padx=(14, 5))
        self.transfer_preset = ttk.Combobox(toolbar, values=("Default",), state="readonly", width=16)
        self.transfer_preset.set("Default")
        self.transfer_preset.pack(side="left")
        ttk.Button(toolbar, text="Refresh", style="Toolbar.TButton", command=self._refresh_all).pack(side="right")

        self.tabs = ttk.Notebook(self, height=1)
        self.tabs.pack(fill="x", pady=(1, 0))
        welcome = ttk.Frame(self.tabs)
        self.tabs.add(welcome, text="  Local ↔ Remote  ")
        self.tabs.bind("<<NotebookTabChanged>>", self._tab_changed)

        panes = ttk.Panedwindow(self, orient="horizontal", style="Dark.TPanedwindow")
        panes.pack(fill="both", expand=True, padx=4, pady=(4, 0))
        left, right = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=1)
        self.local_status = tk.StringVar(value="0 items")
        self.remote_status = tk.StringVar(value="Not connected")
        self.local_tree = self._pane(left, "LOCAL", self.local_path_var, self._local_go, remote=False)
        self.remote_tree = self._pane(right, "REMOTE", self.remote_path_var, self._remote_go, remote=True)
        self.local_tree.bind("<Double-1>", self._local_open)
        self.remote_tree.bind("<Double-1>", self._remote_open)

        self.queue_frame = ttk.LabelFrame(self, text=_("Transfers"), padding=4)
        self.transfer_tree = ttk.Treeview(self.queue_frame, columns=("state", "progress"), show="headings", height=3)
        self.transfer_tree.heading("state", text="State")
        self.transfer_tree.heading("progress", text="Transfer")
        self.transfer_tree.column("state", width=100, stretch=False)
        self.transfer_tree.pack(fill="x")
        self._queue_visible = False
        self.status = tk.StringVar(value=_("Ready"))
        self.status_bar = ttk.Frame(self, style="Status.TFrame", padding=(7, 4))
        self.status_bar.pack(fill="x", pady=(3, 0))
        ttk.Label(self.status_bar, textvariable=self.status, anchor="w", style="Status.TLabel").pack(
            side="left", fill="x", expand=True
        )
        self.update_button = ttk.Button(
            self.status_bar,
            text="Check for updates",
            command=self._update_clicked,
        )
        self.update_button.pack(side="right")

    def _configure_theme(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        c = self.colors
        self.option_add("*Font", (self.ui_font, 9))
        self.option_add("*TCombobox*Listbox.background", c["panel"])
        self.option_add("*TCombobox*Listbox.foreground", c["text"])
        style.configure(".", background=c["surface"], foreground=c["text"], fieldbackground=c["panel"])
        style.configure("TFrame", background=c["surface"])
        style.configure("Card.TFrame", background=c["panel_alt"])
        style.configure("Toolbar.TFrame", background="#2b2d2f")
        style.configure("Status.TFrame", background="#111315")
        style.configure("TLabel", background=c["surface"], foreground=c["text"])
        style.configure("Card.TLabel", background=c["panel_alt"], foreground=c["text"])
        style.configure("Toolbar.TLabel", background="#2b2d2f", foreground=c["text"])
        style.configure("Status.TLabel", background="#111315", foreground=c["muted"])
        style.configure("Section.TLabel", background=c["surface"], foreground="#7fc8ff", font=(self.ui_font, 9, "bold"))
        style.configure("Muted.TLabel", background=c["panel_alt"], foreground=c["muted"])
        style.configure(
            "TButton", background=c["panel_alt"], foreground=c["text"], bordercolor=c["border"], padding=(8, 5)
        )
        style.map("TButton", background=[("active", "#34383c"), ("pressed", "#131517")])
        style.configure("Toolbar.TButton", background="#2b2d2f", padding=(8, 5))
        style.map("Toolbar.TButton", background=[("active", "#3a3e42")])
        style.configure("Accent.TButton", background=c["accent"], foreground="#ffffff", bordercolor=c["accent"])
        style.map("Accent.TButton", background=[("active", c["accent_hover"]), ("pressed", "#0d65aa")])
        style.configure("Update.TButton", foreground=c["warning"])
        style.configure("TEntry", fieldbackground=c["panel"], foreground=c["text"], insertcolor=c["text"], padding=5)
        style.configure("TCombobox", fieldbackground=c["panel"], foreground=c["text"], arrowcolor=c["text"], padding=4)
        style.map("TCombobox", fieldbackground=[("readonly", c["panel"])], foreground=[("readonly", c["text"])])
        style.configure(
            "Treeview",
            background=c["panel"],
            fieldbackground=c["panel"],
            foreground=c["text"],
            rowheight=24,
            borderwidth=0,
        )
        style.map("Treeview", background=[("selected", c["accent"])], foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading", background="#111315", foreground=c["text"], relief="flat", padding=(6, 5))
        style.map("Treeview.Heading", background=[("active", "#303438")])
        style.configure("TNotebook", background=c["surface"], borderwidth=0)
        style.configure("TNotebook.Tab", background="#25282b", foreground=c["muted"], padding=(14, 6))
        style.map("TNotebook.Tab", background=[("selected", "#303438")], foreground=[("selected", c["text"])])
        style.configure("TLabelframe", background=c["surface"], foreground=c["muted"], bordercolor=c["border"])
        style.configure("TLabelframe.Label", background=c["surface"], foreground=c["muted"])
        style.configure("Dark.TPanedwindow", background=c["border"])

    def _build_menu(self) -> None:
        c = self.colors

        def themed_menu(parent: tk.Misc) -> tk.Menu:
            return tk.Menu(
                parent,
                tearoff=False,
                background="#0f1113",
                foreground=c["text"],
                activebackground=c["accent"],
                activeforeground="#ffffff",
                borderwidth=0,
            )

        menu = themed_menu(self)
        session = themed_menu(menu)
        session.add_command(label="New session…", command=self._show_login_dialog, accelerator="Ctrl+N")
        session.add_command(label="Save current site", command=self._save_profile, accelerator="Ctrl+S")
        session.add_command(label="Import WinSCP INI…", command=self._import_winscp_ini)
        session.add_separator()
        session.add_command(label="Save workspace…", command=self._save_workspace)
        session.add_command(label="Open workspace…", command=self._open_workspace)
        session.add_separator()
        session.add_command(label="Exit", command=self._close)
        menu.add_cascade(label="Session", menu=session)
        local = themed_menu(menu)
        local.add_command(label="Parent directory", command=self._local_parent, accelerator="Alt+Up")
        local.add_command(label="Home directory", command=self._local_home)
        local.add_command(label="Refresh", command=self._refresh_local, accelerator="F5")
        local.add_command(label="Upload selected", command=self._upload, accelerator="F6")
        menu.add_cascade(label="Local", menu=local)
        remote = themed_menu(menu)
        remote.add_command(label="Parent directory", command=self._remote_parent)
        remote.add_command(label="Refresh", command=self._refresh_remote)
        remote.add_separator()
        remote.add_command(label="Download selected", command=self._download)
        remote.add_command(label="Edit selected", command=self._remote_edit)
        remote.add_command(label="Rename selected", command=self._remote_rename)
        remote.add_command(label="Delete selected", command=self._remote_delete)
        remote.add_command(label="New directory…", command=self._remote_mkdir)
        menu.add_cascade(label="Remote", menu=remote)
        commands = themed_menu(menu)
        commands.add_command(label="Synchronize…", command=self._sync)
        commands.add_command(label="Show/hide transfer queue", command=self._toggle_queue)
        commands.add_command(label="Check for updates", command=lambda: self._check_for_updates(manual=True))
        menu.add_cascade(label="Commands", menu=commands)
        tabs = themed_menu(menu)
        tabs.add_command(label="New session…", command=self._show_login_dialog)
        tabs.add_command(label="Close active tab", command=self._close_tab, accelerator="Ctrl+W")
        menu.add_cascade(label="Tabs", menu=tabs)
        help_menu = themed_menu(menu)
        help_menu.add_command(label="About DebSCP", command=self._show_about)
        menu.add_cascade(label="Help", menu=help_menu)
        menu_bar = tk.Frame(self, background="#0f1113", height=26)
        menu_bar.pack(fill="x")
        for label, submenu in (
            ("Session", session),
            ("Local", local),
            ("Remote", remote),
            ("Commands", commands),
            ("Tabs", tabs),
            ("Help", help_menu),
        ):
            button = tk.Menubutton(
                menu_bar,
                text=label,
                menu=submenu,
                background="#0f1113",
                foreground=c["text"],
                activebackground=c["accent"],
                activeforeground="#ffffff",
                borderwidth=0,
                highlightthickness=0,
                relief="flat",
                padx=7,
                pady=4,
            )
            button.pack(side="left")
        self.bind("<Control-n>", lambda _event: self._show_login_dialog())
        self.bind("<Control-s>", lambda _event: self._save_profile())
        self.bind("<Control-w>", lambda _event: self._close_tab())
        self.bind("<F5>", lambda _event: self._refresh_all())
        self.bind("<F6>", lambda _event: self._upload())

    def _pane(
        self,
        parent: ttk.Frame,
        title: str,
        path_var: tk.StringVar,
        go: Callable[[], object],
        *,
        remote: bool,
    ) -> ttk.Treeview:
        header = ttk.Frame(parent, style="Toolbar.TFrame", padding=(5, 4))
        header.pack(fill="x")
        ttk.Label(header, text=title, style="Section.TLabel").pack(side="left", padx=(2, 9))
        if remote:
            ttk.Button(header, text="Download", style="Toolbar.TButton", command=self._download).pack(side="left")
            ttk.Button(header, text="Edit", style="Toolbar.TButton", command=self._remote_edit).pack(side="left")
            ttk.Button(header, text="Delete", style="Toolbar.TButton", command=self._remote_delete).pack(side="left")
            ttk.Button(header, text="New folder", style="Toolbar.TButton", command=self._remote_mkdir).pack(side="left")
        else:
            ttk.Button(header, text="Upload", style="Toolbar.TButton", command=self._upload).pack(side="left")
            ttk.Button(header, text="Home", style="Toolbar.TButton", command=self._local_home).pack(side="left")
        ttk.Button(
            header,
            text="Refresh",
            style="Toolbar.TButton",
            command=self._refresh_remote if remote else self._refresh_local,
        ).pack(side="right")
        ttk.Button(
            header, text="Up", style="Toolbar.TButton", command=self._remote_parent if remote else self._local_parent
        ).pack(side="right")
        bar = ttk.Frame(parent, padding=(4, 4))
        bar.pack(fill="x")
        entry = ttk.Entry(bar, textvariable=path_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _event: go())
        ttk.Button(bar, text="Go", command=go).pack(side="right", padx=(4, 0))
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=("name", "size", "type", "modified"), show="headings", selectmode="browse")
        tree.heading("name", text="Name")
        tree.heading("size", text="Size")
        tree.heading("type", text="Type")
        tree.heading("modified", text="Modified")
        tree.column("name", width=245)
        tree.column("size", width=88, anchor="e", stretch=False)
        tree.column("type", width=110, stretch=False)
        tree.column("modified", width=145, stretch=False)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        pane_status = self.remote_status if remote else self.local_status
        ttk.Label(parent, textvariable=pane_status, style="Status.TLabel", padding=(5, 3)).pack(fill="x")
        return tree

    def _toggle_queue(self) -> None:
        if self._queue_visible:
            self.queue_frame.pack_forget()
        else:
            self.queue_frame.pack(fill="x", padx=4, pady=(4, 0), before=self.status_bar)
        self._queue_visible = not self._queue_visible

    def _local_parent(self) -> None:
        if self.local_path.parent != self.local_path:
            self.local_path = self.local_path.parent
            self._refresh_local()

    def _local_home(self) -> None:
        self.local_path = Path.home()
        self._refresh_local()

    def _remote_parent(self) -> None:
        if self.backend and self.remote_path != "/":
            self.remote_path_var.set(str(PurePosixPath(self.remote_path).parent))
            self._remote_go()

    def _show_about(self) -> None:
        messagebox.showinfo(
            "About DebSCP",
            f"DebSCP {__version__}\n\nNative Linux dual-pane file transfer client.\n"
            "SFTP • SCP • FTP/FTPS • WebDAV • S3",
            parent=self,
        )

    def _load_session_names(self) -> None:
        self.sessions = self.store.load()
        self.profile_box["values"] = [item.name for item in self.sessions]

    def _show_login_dialog(self) -> None:
        for child in self.winfo_children():
            if isinstance(child, LoginDialog):
                child.lift()
                return
        LoginDialog(
            self,
            self.store,
            self.credential_store,
            self._login_from_dialog,
            self._show_quick_connect,
            self._open_workspace_named,
            self._import_winscp_ini,
        )

    def _show_quick_connect(self) -> None:
        self.deiconify()
        self.lift()

    def _login_from_dialog(self, config: SessionConfig, password: str | None) -> None:
        self.deiconify()
        self.session_name.set(config.name)
        self.host.set(config.host)
        self.port.set(str(config.port))
        self.username.set(config.username)
        self.password.set(password or "")
        self.protocol_name.set(config.protocol)
        self.key_file.set(config.key_file or "")
        self.remote_path_var.set(config.remote_path)
        self.status.set(f"Connecting to {config.host}…")
        self._background(lambda: self._connect_worker(config, password))

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

    def _connect(self) -> bool:
        try:
            config = self._config()
            password = self.password.get() or self.credential_store.get(config.name)
        except (RuntimeError, ValueError) as exc:
            messagebox.showerror("Invalid connection", str(exc), parent=self)
            return False
        if config.protocol == "ftp" and not messagebox.askyesno(
            "Unencrypted FTP",
            "FTP sends credentials and file data without encryption. Continue anyway?\n\nUse FTPS or SFTP when possible.",
            icon="warning",
            parent=self,
        ):
            return False
        self.status.set(f"Connecting to {config.host}…")
        self._background(lambda: self._connect_worker(config, password))
        return True

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
        self.remote_status.set(
            f"{len(entries)} items • {display_size(sum(item.size for item in entries if not item.is_dir))}"
        )
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

    def _check_for_updates(self, manual: bool = False) -> None:
        if self.closing or self._update_checking:
            return
        if self._next_update_check:
            self.after_cancel(self._next_update_check)
            self._next_update_check = None
        self._update_checking = True
        self.update_button.configure(state="disabled", text="Checking…")

        def check() -> None:
            try:
                update = check_for_update(__version__)
            except Exception as exc:  # noqa: BLE001 - an update failure must never disrupt file transfers
                self.after(0, self._update_check_finished, None, exc, manual)
            else:
                self.after(0, self._update_check_finished, update, None, manual)

        self._background(check)

    def _update_check_finished(
        self,
        update: UpdateInfo | None,
        error: Exception | None,
        manual: bool,
    ) -> None:
        self._update_checking = False
        if self.closing:
            return
        if error:
            self.update_button.configure(state="normal", text="Check for updates", style="TButton")
            if manual:
                messagebox.showerror("Update check failed", str(error), parent=self)
        elif update:
            self.available_update = update
            self.update_button.configure(state="normal", style="Update.TButton")
            if not self._update_flash_running:
                self._update_flash_running = True
                self._flash_update_button()
        else:
            self.available_update = None
            self.update_button.configure(state="normal", text="Up to date", style="TButton")
            if manual:
                messagebox.showinfo("DebSCP update", f"DebSCP {__version__} is up to date.", parent=self)
            self.after(3000, self._restore_update_button)
        self._next_update_check = self.after(6 * 60 * 60 * 1000, self._check_for_updates)

    def _restore_update_button(self) -> None:
        if not self.closing and not self.available_update and not self._update_checking:
            self.update_button.configure(text="Check for updates")

    def _flash_update_button(self) -> None:
        if self.closing or not self.available_update:
            self._update_flash_running = False
            return
        if self._update_checking:
            self.after(650, self._flash_update_button)
            return
        self._update_flash_on = not self._update_flash_on
        text = (
            f"● Update v{self.available_update.version}"
            if self._update_flash_on
            else f"Update available: v{self.available_update.version}"
        )
        self.update_button.configure(text=text)
        self.after(650, self._flash_update_button)

    def _update_clicked(self) -> None:
        if not self.available_update:
            self._check_for_updates(manual=True)
            return
        update = self.available_update
        size_mib = update.size / (1024 * 1024)
        if not messagebox.askyesno(
            "Install DebSCP update",
            f"Download and install DebSCP {update.version} ({size_mib:.1f} MiB)?\n\n"
            "The package will be verified before PolicyKit asks for administrator approval. "
            "DebSCP will close before the installer starts.",
            parent=self,
        ):
            return
        self.update_button.configure(state="disabled", text="Downloading…")
        self.status.set(f"Downloading DebSCP {update.version}…")

        def progress(received: int, total: int) -> None:
            percent = int(received * 100 / total)
            if not self.closing:
                self.after(0, self.status.set, f"Downloading DebSCP {update.version}: {percent}%")

        def fetch() -> None:
            try:
                package = download_update(update, progress=progress)
                verify_debian_package(package, update)
            except Exception as exc:  # noqa: BLE001 - restore the update control after any download failure
                self.after(0, self._update_download_failed, exc)
            else:
                self.after(0, self._launch_update, package, update)

        self._background(fetch)

    def _update_download_failed(self, error: Exception) -> None:
        if self.closing:
            return
        self.update_button.configure(state="normal")
        self.status.set("Update download or verification failed")
        messagebox.showerror("Cannot install update", str(error), parent=self)

    def _launch_update(self, package: Path, update: UpdateInfo) -> None:
        if self.closing:
            return
        try:
            self._update_helper = launch_installer_after_exit(package, update)
        except (OSError, RuntimeError, ValueError) as exc:
            self.update_button.configure(state="normal")
            self.status.set("Update installation could not start")
            messagebox.showerror("Cannot install update", str(exc), parent=self)
            return
        self.status.set(f"Installing DebSCP {update.version}; closing…")
        self._close()

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
            self.local_tree.insert("", "end", iid="..", values=("..", "", "Parent directory", ""))
        try:
            entries = sorted(self.local_path.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
        except OSError as exc:
            messagebox.showerror("Local folder", str(exc), parent=self)
            return
        total_size = 0
        for item in entries:
            try:
                details = item.stat()
                size = "" if item.is_dir() else display_size(details.st_size)
                if not item.is_dir():
                    total_size += details.st_size
                modified = datetime.fromtimestamp(details.st_mtime, UTC).astimezone().strftime("%d/%m/%Y %H:%M")
            except OSError:
                size, modified = "?", "?"
            self.local_tree.insert("", "end", iid=item.name, values=(item.name, size, local_type(item), modified))
        self.local_status.set(f"{len(entries)} items • {display_size(total_size)}")

    def _show_remote(self, entries: list[RemoteEntry]) -> None:
        self.remote_tree.delete(*self.remote_tree.get_children())
        self.remote_entries = {entry.name: entry for entry in entries}
        if self.remote_path != "/":
            self.remote_tree.insert("", "end", iid="..", values=("..", "", "Parent directory", ""))
        for entry in entries:
            self.remote_tree.insert(
                "",
                "end",
                iid=entry.name,
                values=(
                    entry.name,
                    "" if entry.is_dir else entry.display_size,
                    "File folder" if entry.is_dir else "File",
                    entry.modified.strftime("%d/%m/%Y %H:%M"),
                ),
            )
        total_size = sum(entry.size for entry in entries if not entry.is_dir)
        self.remote_status.set(f"{len(entries)} items • {display_size(total_size)}")

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
        self.remote_status.set("Not connected")
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
        self._open_workspace_named(name)

    def _open_workspace_named(self, name: str) -> None:
        self.deiconify()
        workspaces = WorkspaceStore().load()
        if name not in workspaces:
            messagebox.showerror("Workspace", f"Workspace {name!r} no longer exists.", parent=self)
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
        if not self._queue_visible:
            self._toggle_queue()
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
