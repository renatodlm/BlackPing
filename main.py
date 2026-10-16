"""Janela leve para medir o ping das conexões do Black Desert."""

from __future__ import annotations

import ctypes
import queue
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
import tkinter as tk

import customtkinter as ctk
import psutil

INTERVAL_S = 3.0
PROBE_TIMEOUT_S = 1.0
GAME_PROCESS = "blackdesert64.exe"
ICON_PATH = Path(__file__).resolve().with_name("blackping.ico")
ICON_PNG = Path(__file__).resolve().with_name("blackping.png")

GREEN = "#b6ff4a"
YELLOW = "#ffcc33"
RED = "#ff4d4d"
MUTED = "#8d866f"
CARD = "#12140f"
LINE = "#3a3424"
TEXT = "#f3ecd8"
SUBTLE = "#b7aa8c"
BG = "#070806"
GOLD = "#e2c27a"
GOLD_DIM = "#6e5a32"

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
GA_ROOT = 2
PASS_THROUGH = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW

user32 = ctypes.windll.user32
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.SetLayeredWindowAttributes.argtypes = [
    wintypes.HWND,
    wintypes.COLORREF,
    wintypes.BYTE,
    wintypes.DWORD,
]
user32.SetLayeredWindowAttributes.restype = wintypes.BOOL


def role_for(port: int) -> str:
    if 8880 <= port <= 8899:
        return "jogo"
    if port == 443:
        return "web"
    return "tcp"


def color_for(ms: float | None) -> str:
    if ms is None:
        return MUTED
    if ms < 80:
        return GREEN
    if ms <= 120:
        return YELLOW
    return RED


def probe(ip: str, port: int, timeout: float = PROBE_TIMEOUT_S) -> float | None:
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    started = time.perf_counter()
    try:
        sock.connect((ip, port))
    except OSError:
        return None
    else:
        return (time.perf_counter() - started) * 1000
    finally:
        sock.close()


def game_pids() -> set[int]:
    pids: set[int] = set()
    for proc in psutil.process_iter(["pid", "name"]):
        name = (proc.info["name"] or "").lower()
        if name == GAME_PROCESS:
            pids.add(proc.info["pid"])
    return pids


def established_targets(pids: set[int]) -> list[tuple[str, int]]:
    found: set[tuple[str, int]] = set()
    for conn in psutil.net_connections(kind="tcp"):
        if conn.pid not in pids or conn.status != psutil.CONN_ESTABLISHED:
            continue
        remote = conn.raddr
        if not remote or not remote.ip or remote.port <= 0:
            continue
        if remote.ip in {"0.0.0.0", "127.0.0.1", "::", "::1"}:
            continue
        found.add((remote.ip, remote.port))
    return sorted(found, key=lambda item: (role_for(item[1]) != "jogo", item[1], item[0]))


ROLE_ORDER = ("jogo", "web", "tcp")


def display_rows(conns: list[dict], grouped: bool, show_ips: bool) -> list[dict]:
    if grouped:
        buckets: dict[str, list[dict]] = {}
        for conn in conns:
            buckets.setdefault(conn["role"], []).append(conn)
        roles = [role for role in ROLE_ORDER if role in buckets]
        roles.extend(role for role in buckets if role not in ROLE_ORDER)
        rows = []
        for role in roles:
            group = buckets[role]
            samples = [item["ms"] for item in group if item["ms"] is not None]
            average = sum(samples) / len(samples) if samples else None
            if show_ips:
                extra = group[0]["ip"] if len(group) == 1 else f"{group[0]['ip']} +{len(group) - 1}"
            elif len(group) > 1:
                extra = "média"
            else:
                extra = str(group[0]["port"])
            rows.append({
                "key": ("tipo", role),
                "ms": average,
                "title": role.upper(),
                "meta": extra,
            })
        return rows

    rows = []
    for conn in conns:
        if show_ips:
            title = conn["ip"]
            meta = f"{conn['port']}  {conn['role'].upper()}"
        else:
            title = conn["role"].upper()
            meta = str(conn["port"])
        rows.append({
            "key": (conn["ip"], conn["port"]),
            "ms": conn["ms"],
            "title": title,
            "meta": meta,
        })
    return rows


def collect() -> dict:
    now = datetime.now().strftime("%H:%M:%S")
    try:
        pids = game_pids()
    except psutil.Error as exc:
        return {"running": False, "conns": [], "error": str(exc), "at": now}
    if not pids:
        return {"running": False, "conns": [], "error": None, "at": now}
    try:
        targets = established_targets(pids)
    except psutil.Error as exc:
        return {"running": True, "conns": [], "error": str(exc), "at": now}

    measured: list[dict] = []
    if targets:
        with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
            futures = {pool.submit(probe, ip, port): (ip, port) for ip, port in targets}
            for future in as_completed(futures):
                ip, port = futures[future]
                try:
                    ms = future.result()
                except OSError:
                    ms = None
                measured.append({"ip": ip, "port": port, "ms": ms, "role": role_for(port)})
    measured.sort(key=lambda row: (row["role"] != "jogo", row["port"], row["ip"]))
    return {"running": True, "conns": measured, "error": None, "at": now}


class ConnRow(ctk.CTkFrame):
    def __init__(self, master, conn: dict):
        super().__init__(master, fg_color=CARD, corner_radius=2, border_width=1, border_color=LINE)
        self.grid_columnconfigure(2, weight=1)

        self.bar = ctk.CTkFrame(self, width=3, height=16, corner_radius=0, fg_color=MUTED)
        self.bar.grid(row=0, column=0, padx=(8, 6), pady=7)
        self.bar.grid_propagate(False)

        self.ms = ctk.CTkLabel(
            self,
            text="",
            width=54,
            anchor="w",
            font=ctk.CTkFont(family="Consolas", size=14, weight="bold"),
        )
        self.ms.grid(row=0, column=1, sticky="w")

        self.addr = ctk.CTkLabel(
            self,
            text="",
            anchor="w",
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color=TEXT,
        )
        self.addr.grid(row=0, column=2, sticky="ew", padx=(6, 4))

        self.meta = ctk.CTkLabel(
            self,
            text="",
            anchor="e",
            font=ctk.CTkFont(family="Bahnschrift", size=11),
            text_color=SUBTLE,
        )
        self.meta.grid(row=0, column=3, sticky="e", padx=(4, 8))
        self.update_conn(conn)

    def update_conn(self, conn: dict) -> None:
        ms = conn["ms"]
        color = color_for(ms)
        self.ms.configure(text="--" if ms is None else f"{round(ms)}ms", text_color=color)
        self.addr.configure(text=conn["title"])
        self.meta.configure(text=conn["meta"])
        self.bar.configure(fg_color=color)


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("BlackPing")
        self.geometry("372x248")
        self.minsize(320, 148)
        self.configure(fg_color=BG)
        self._apply_icon()

        self.stop = threading.Event()
        self.events: queue.Queue = queue.Queue()
        self.cards: dict[tuple, ConnRow] = {}
        self.placeholder: ctk.CTkLabel | None = None
        self._snapshot: dict | None = None
        self.overlay = False
        self._sized_once = False
        self.hit_window: ctk.CTkToplevel | None = None

        self.shell = ctk.CTkFrame(self, fg_color=BG, corner_radius=0, border_width=1, border_color=LINE)
        self.shell.pack(fill="both", expand=True)

        ctk.CTkFrame(self.shell, height=2, fg_color=GOLD, corner_radius=0).pack(fill="x")

        header = ctk.CTkFrame(self.shell, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=(6, 2))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="BLACKPING",
            anchor="w",
            font=ctk.CTkFont(family="Bahnschrift", size=13, weight="bold"),
            text_color=GOLD,
        ).grid(row=0, column=0, sticky="w")

        self.status = ctk.CTkLabel(
            header,
            text="LENDO",
            anchor="w",
            font=ctk.CTkFont(family="Bahnschrift", size=11),
            text_color=SUBTLE,
        )
        self.status.grid(row=0, column=1, sticky="w", padx=(8, 6))

        self.top_switch = ctk.CTkSwitch(
            header,
            text="no topo",
            command=self.toggle_top,
            font=ctk.CTkFont(family="Bahnschrift", size=11),
            text_color=SUBTLE,
            progress_color=GOLD,
            button_color=GOLD,
            button_hover_color="#f0d7a0",
            width=96,
            height=22,
            switch_width=32,
            switch_height=16,
        )
        self.top_switch.grid(row=0, column=2, sticky="e")

        self.unpin_button = ctk.CTkButton(
            header,
            text="desafixar",
            width=76,
            height=22,
            corner_radius=2,
            fg_color="#1a160d",
            hover_color="#3a3018",
            border_width=1,
            border_color=GOLD,
            text_color=GOLD,
            font=ctk.CTkFont(family="Bahnschrift", size=11, weight="bold"),
            command=self.unpin,
        )
        self.unpin_button.grid(row=0, column=2, sticky="e")
        self.unpin_button.grid_remove()

        self.options = ctk.CTkFrame(self.shell, fg_color="transparent")
        self.options.pack(fill="x", padx=8, pady=(0, 2))

        switch_font = ctk.CTkFont(family="Bahnschrift", size=11)
        self.group_switch = ctk.CTkSwitch(
            self.options,
            text="média",
            command=self._refresh_view,
            font=switch_font,
            text_color=SUBTLE,
            progress_color=GOLD,
            button_color=GOLD,
            button_hover_color="#f0d7a0",
            width=84,
            height=22,
            switch_width=32,
            switch_height=16,
        )
        self.group_switch.pack(side="left")
        self.group_switch.select()

        self.ip_switch = ctk.CTkSwitch(
            self.options,
            text="ips",
            command=self._refresh_view,
            font=switch_font,
            text_color=SUBTLE,
            progress_color=GOLD,
            button_color=GOLD,
            button_hover_color="#f0d7a0",
            width=68,
            height=22,
            switch_width=32,
            switch_height=16,
        )
        self.ip_switch.pack(side="left", padx=(10, 0))

        self.body = ctk.CTkFrame(self.shell, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=8, pady=(2, 8))
        self.body.grid_columnconfigure(0, weight=1)

        self.after(200, self._apply_icon)
        self.worker = threading.Thread(target=self.loop, name="blackping", daemon=True)
        self.worker.start()
        self.after(150, self.poll)
        self.bind("<Escape>", self._on_escape)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _widget_hwnd(self, widget) -> int:
        hwnd = int(widget.winfo_id())
        root = user32.GetAncestor(hwnd, GA_ROOT)
        if root:
            return int(root)
        parent = user32.GetParent(hwnd)
        return int(parent or hwnd)

    def _top_hwnd(self) -> int:
        return self._widget_hwnd(self)

    def _set_mouse_passthrough(self, enabled: bool) -> None:
        hwnd = self._top_hwnd()
        if enabled:
            self.attributes("-alpha", 0.6)
            self.update_idletasks()
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if enabled:
            style |= PASS_THROUGH
            style &= ~WS_EX_APPWINDOW
        else:
            style &= ~PASS_THROUGH
            style |= WS_EX_APPWINDOW
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
        if enabled:
            user32.SetLayeredWindowAttributes(hwnd, 0, 153, 0x2)
        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED
        user32.SetWindowPos(hwnd, HWND_TOPMOST if enabled else HWND_NOTOPMOST, 0, 0, 0, 0, flags)
        if not enabled:
            self.attributes("-alpha", 1.0)

    def _ensure_hit_window(self) -> None:
        if self.hit_window is not None:
            return
        win = ctk.CTkToplevel(self)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(fg_color="#1a160d")
        win.title("")
        self.hit_button = ctk.CTkButton(
            win,
            text="desafixar",
            width=76,
            height=22,
            corner_radius=2,
            fg_color="#1a160d",
            hover_color="#3a3018",
            border_width=1,
            border_color=GOLD,
            text_color=GOLD,
            font=ctk.CTkFont(family="Bahnschrift", size=11, weight="bold"),
            command=self.unpin,
        )
        self.hit_button.pack(fill="both", expand=True)
        self.hit_window = win

    def _style_hit_window(self) -> None:
        if self.hit_window is None:
            return
        hwnd = self._widget_hwnd(self.hit_window)
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_LAYERED
        style &= ~(WS_EX_TRANSPARENT | WS_EX_APPWINDOW)
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
        user32.SetLayeredWindowAttributes(hwnd, 0, 1, 0x2)

    def _place_hit_button(self) -> None:
        if not self.overlay or self.hit_window is None or not self.unpin_button.winfo_ismapped():
            return
        self.update_idletasks()
        x = self.unpin_button.winfo_rootx()
        y = self.unpin_button.winfo_rooty()
        width = max(76, self.unpin_button.winfo_width())
        height = max(22, self.unpin_button.winfo_height())
        hwnd = self._widget_hwnd(self.hit_window)
        user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST,
            x,
            y,
            width,
            height,
            SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )
        self._style_hit_window()

    def _hide_hit_button(self) -> None:
        if self.hit_window is not None:
            self.hit_window.withdraw()

    def _fit_overlay(self) -> None:
        if not self.overlay or not self.winfo_exists():
            return
        self.update_idletasks()
        width = 360
        height = max(92, self.shell.winfo_reqheight())
        x, y = self.winfo_x(), self.winfo_y()
        self.geometry(f"{width}x{height}+{x}+{y}")
        self._place_hit_button()

    def _apply_overlay_chrome(self, enabled: bool) -> None:
        if enabled:
            self.top_switch.grid_remove()
            self.unpin_button.grid()
            self.options.pack_forget()
            return
        self.unpin_button.grid_remove()
        self.top_switch.grid()
        self.options.pack(fill="x", padx=8, pady=(0, 2), before=self.body)

    def toggle_top(self) -> None:
        self._set_overlay(bool(self.top_switch.get()))

    def unpin(self) -> None:
        if bool(self.top_switch.get()):
            self.top_switch.deselect()
        self._set_overlay(False)

    def _on_escape(self, _event=None):
        if self.overlay:
            self.unpin()

    def _set_overlay(self, enabled: bool) -> None:
        if enabled == self.overlay:
            return
        self.update_idletasks()
        x, y = self.winfo_x(), self.winfo_y()
        width = 360 if enabled else max(360, self.winfo_width())
        height = self.winfo_height()
        self.withdraw()
        self.overlay = enabled
        self.overrideredirect(enabled)
        self._apply_overlay_chrome(enabled)
        if enabled:
            self.geometry(f"+{x}+{y}")
        else:
            self.geometry(f"{width}x{max(height, 180)}+{x}+{y}")
            self.minsize(320, 148)
        self.deiconify()
        self.attributes("-topmost", enabled)
        self.update_idletasks()
        self._set_mouse_passthrough(enabled)
        if enabled:
            self._ensure_hit_window()
            self._fit_overlay()
            self._place_hit_button()
            self.after(120, self._place_hit_button)
        else:
            self._hide_hit_button()
        self._apply_icon()

    def _apply_icon(self) -> None:
        if not ICON_PATH.is_file() or not self.winfo_exists():
            return
        try:
            if ICON_PATH.is_file():
                self.iconbitmap(default=str(ICON_PATH))
            if ICON_PNG.is_file():
                self._icon_image = tk.PhotoImage(file=str(ICON_PNG))
                self.iconphoto(True, self._icon_image)
        except tk.TclError:
            return

    def loop(self) -> None:
        while not self.stop.is_set():
            started = time.perf_counter()
            try:
                snapshot = collect()
            except Exception as exc:
                snapshot = {
                    "running": False,
                    "conns": [],
                    "error": str(exc),
                    "at": datetime.now().strftime("%H:%M:%S"),
                }
            self.events.put(snapshot)
            remaining = INTERVAL_S - (time.perf_counter() - started)
            self.stop.wait(max(0.4, remaining))

    def poll(self) -> None:
        latest = None
        try:
            while True:
                latest = self.events.get_nowait()
        except queue.Empty:
            pass
        if latest is not None:
            self.render(latest)
        if not self.stop.is_set():
            self.after(150, self.poll)

    def _grouped(self) -> bool:
        return bool(self.group_switch.get())

    def _show_ips(self) -> bool:
        return bool(self.ip_switch.get())

    def _refresh_view(self) -> None:
        self.cards = {}
        if self._snapshot is not None:
            self.render(self._snapshot)

    def render(self, snapshot: dict) -> None:
        self._snapshot = snapshot
        conns = display_rows(snapshot["conns"], self._grouped(), self._show_ips())
        if snapshot["error"]:
            status = f"SEM ACESSO  {snapshot['at']}"
        elif not snapshot["running"]:
            status = f"OFFLINE  {snapshot['at']}"
        elif not snapshot["conns"]:
            status = f"SEM LINK  {snapshot['at']}"
        else:
            status = f"{len(snapshot['conns'])} LINKS  {snapshot['at']}"
        self.status.configure(text=status)

        keys = [conn["key"] for conn in conns]
        if keys and keys == list(self.cards):
            by_key = {conn["key"]: conn for conn in conns}
            for key, card in self.cards.items():
                card.update_conn(by_key[key])
            return
        if not keys and self.placeholder is not None and not self.cards:
            return

        for child in self.body.winfo_children():
            child.destroy()
        self.cards = {}
        self.placeholder = None

        if not conns:
            if snapshot["error"]:
                message = "Sem permissão para ler as conexões."
            elif snapshot["running"]:
                message = "Jogo aberto, sem conexão TCP."
            else:
                message = "Abra o Black Desert."
            self.placeholder = ctk.CTkLabel(
                self.body,
                text=message,
                font=ctk.CTkFont(family="Bahnschrift", size=12),
                text_color=SUBTLE,
                wraplength=300,
                justify="left",
            )
            self.placeholder.grid(row=0, column=0, sticky="ew", padx=4, pady=8)
            if self.overlay:
                self.after_idle(self._fit_overlay)
            return

        for index, conn in enumerate(conns):
            card = ConnRow(self.body, conn)
            card.grid(row=index, column=0, sticky="ew", pady=2)
            self.cards[(conn["ip"], conn["port"])] = card
        if self.overlay:
            self.after_idle(self._fit_overlay)
        elif not self._sized_once:
            self._sized_once = True
            self.after_idle(self._fit_normal)

    def _fit_normal(self) -> None:
        if self.overlay or not self.winfo_exists():
            return
        self.update_idletasks()
        height = min(420, max(168, self.shell.winfo_reqheight() + 8))
        x, y = self.winfo_x(), self.winfo_y()
        self.geometry(f"372x{height}+{x}+{y}")

    def on_close(self) -> None:
        self.stop.set()
        self.destroy()


def main() -> None:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("renatodlm.BlackPing")
    except OSError:
        pass
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    App().mainloop()


if __name__ == "__main__":
    main()
