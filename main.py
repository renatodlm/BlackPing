"""Janela leve para medir o ping das conexões do Black Desert."""

from __future__ import annotations

import queue
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import customtkinter as ctk
import psutil

INTERVAL_S = 3.0
PROBE_TIMEOUT_S = 1.0
GAME_PROCESS = "blackdesert64.exe"

GREEN = "#3fb950"
YELLOW = "#d29922"
RED = "#f85149"
MUTED = "#8b949e"
CARD = "#161b22"
BORDER = "#30363d"
TEXT = "#e6edf3"
SUBTLE = "#9da7b3"
BG = "#0d1117"


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


class ConnCard(ctk.CTkFrame):
    def __init__(self, master, conn: dict):
        super().__init__(master, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER)
        self.grid_columnconfigure(1, weight=1)

        self.bar = ctk.CTkFrame(self, width=4, height=36, corner_radius=4, fg_color=MUTED)
        self.bar.grid(row=0, column=0, rowspan=2, sticky="nsw", padx=(14, 12), pady=14)
        self.bar.grid_propagate(False)

        self.addr = ctk.CTkLabel(
            self,
            text="",
            anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color=TEXT,
        )
        self.addr.grid(row=0, column=1, sticky="ew", pady=(12, 0))

        self.meta = ctk.CTkLabel(
            self,
            text="",
            anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=SUBTLE,
        )
        self.meta.grid(row=1, column=1, sticky="ew", pady=(0, 12))

        self.ms = ctk.CTkLabel(
            self,
            text="",
            anchor="e",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
        )
        self.ms.grid(row=0, column=2, rowspan=2, sticky="e", padx=(8, 16))
        self.update_conn(conn)

    def update_conn(self, conn: dict) -> None:
        ms = conn["ms"]
        color = color_for(ms)
        shown = "—" if ms is None else f"{round(ms)} ms"
        self.addr.configure(text=conn["ip"])
        self.meta.configure(text=f"porta {conn['port']}  ·  {conn['role']}")
        self.ms.configure(text=shown, text_color=color)
        self.bar.configure(fg_color=color)


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("BlackPing")
        self.geometry("460x560")
        self.minsize(400, 420)
        self.configure(fg_color=BG)

        self.stop = threading.Event()
        self.events: queue.Queue = queue.Queue()
        self.cards: dict[tuple[str, int], ConnCard] = {}
        self.placeholder: ctk.CTkLabel | None = None

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(18, 6))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="BlackPing",
            anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=26, weight="bold"),
            text_color=TEXT,
        ).grid(row=0, column=0, sticky="w")

        self.top_switch = ctk.CTkSwitch(
            header,
            text="Sempre no topo",
            command=self.toggle_top,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            progress_color=GREEN,
        )
        self.top_switch.grid(row=0, column=1, sticky="e", padx=(12, 0))

        self.status = ctk.CTkLabel(
            header,
            text="Lendo conexões…",
            anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=SUBTLE,
        )
        self.status.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list.pack(fill="both", expand=True, padx=12, pady=(10, 4))

        self.body = ctk.CTkFrame(self.list, fg_color="transparent")
        self.body.pack(fill="both", expand=True)
        self.body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self,
            text="Tempo de conexão TCP. Os servidores do jogo não respondem ao ping comum.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#6e7681",
            wraplength=410,
            justify="left",
        ).pack(fill="x", padx=22, pady=(4, 16))

        self.worker = threading.Thread(target=self.loop, name="blackping", daemon=True)
        self.worker.start()
        self.after(150, self.poll)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def toggle_top(self) -> None:
        self.attributes("-topmost", bool(self.top_switch.get()))

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

    def render(self, snapshot: dict) -> None:
        conns = snapshot["conns"]
        if snapshot["error"]:
            status = f"Não consegui ler as conexões.  {snapshot['at']}"
        elif not snapshot["running"]:
            status = f"Black Desert fechado  ·  {snapshot['at']}"
        elif not conns:
            status = f"Jogo aberto, sem conexão TCP  ·  {snapshot['at']}"
        else:
            noun = "conexão" if len(conns) == 1 else "conexões"
            status = f"Black Desert  ·  {len(conns)} {noun}  ·  {snapshot['at']}"
        self.status.configure(text=status)

        keys = [(conn["ip"], conn["port"]) for conn in conns]
        if keys and keys == list(self.cards):
            by_key = {(conn["ip"], conn["port"]): conn for conn in conns}
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
                message = "Sem permissão para ler as conexões do jogo."
            elif snapshot["running"]:
                message = "O jogo está aberto, mas não há conexões TCP agora."
            else:
                message = "Abra o Black Desert para ver o ping."
            self.placeholder = ctk.CTkLabel(
                self.body,
                text=message,
                font=ctk.CTkFont(family="Segoe UI", size=14),
                text_color=SUBTLE,
                wraplength=360,
                justify="left",
            )
            self.placeholder.grid(row=0, column=0, sticky="ew", padx=8, pady=28)
            return

        for index, conn in enumerate(conns):
            card = ConnCard(self.body, conn)
            card.grid(row=index, column=0, sticky="ew", pady=5, padx=4)
            self.cards[(conn["ip"], conn["port"])] = card

    def on_close(self) -> None:
        self.stop.set()
        self.destroy()


def main() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    App().mainloop()


if __name__ == "__main__":
    main()
