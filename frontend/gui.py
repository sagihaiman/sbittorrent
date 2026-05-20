import customtkinter as ctk
import threading
import socket
import os
import sys

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

BG         = "#C8922A"
TOOLBAR_BG = "#8B8B2A"
PANEL_BG   = "#9B5E1A"
ROW_BG     = "#7A4010"
ROW_HOVER  = "#6B3508"
ROW_DOWN   = "#7A3A00"
ACCENT     = "#6B0A0A"
TEXT_LIGHT = "#C8922A"
TEXT_BODY  = "#1A0A00"
WHITE      = "#F5E6C8"

FONT_TITLE = ("Impact", 42, "bold")
FONT_BTN   = ("Arial Rounded MT Bold", 14, "bold")
FONT_HEAD  = ("Arial Rounded MT Bold", 13, "bold")
FONT_ROW   = ("Arial", 13, "bold")
FONT_SMALL = ("Arial", 11)

# Column definitions: (header, min_width, weight)
# weight=1 means the column stretches, weight=0 means fixed
COLUMNS = [
    ("Name",    200, 1),
    ("Size",     70, 0),
    ("Chunks",   80, 0),
    ("Status",  110, 0),
    ("Seeds",    55, 0),
    ("Peers",    55, 0),
    ("Leeches",  65, 0),
]
TOTAL_ROWS = 8

def fmt_size(b):
    if b >= 1073741824: return f"{b/1073741824:.1f} GB"
    if b >= 1048576:    return f"{round(b/1048576)} MB"
    if b >= 1024:       return f"{round(b/1024)} KB"
    return f"{b} B"

def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# ─────────────────────────────────────────────
# MODAL BASE
# ─────────────────────────────────────────────

class Modal(ctk.CTkToplevel):
    def __init__(self, parent, title, height=220):
        super().__init__(parent)
        self.title(title)
        self.configure(fg_color=PANEL_BG)
        self.resizable(False, False)
        self.grab_set()
        self.lift()
        self.focus_force()
        self.update_idletasks()
        w = 440
        px = parent.winfo_x() + parent.winfo_width()  // 2
        py = parent.winfo_y() + parent.winfo_height() // 2
        self.geometry(f"{w}x{height}+{px - w//2}+{py - height//2}")

    def _input(self, parent, placeholder):
        e = ctk.CTkEntry(parent, placeholder_text=placeholder,
                         fg_color=ROW_BG, border_color=ROW_HOVER,
                         text_color=WHITE, placeholder_text_color="#9B6030",
                         font=FONT_ROW, corner_radius=10, height=38)
        e.pack(fill="x", pady=(0, 8))
        return e

    def _buttons(self, frame, ok_text, ok_cmd):
        ctk.CTkButton(frame, text="Cancel", command=self.destroy,
                      fg_color=ROW_HOVER, hover_color=ROW_BG,
                      text_color=TEXT_LIGHT, font=FONT_BTN,
                      corner_radius=10, width=100).pack(side="left", padx=(0, 10))
        ctk.CTkButton(frame, text=ok_text, command=ok_cmd,
                      fg_color=ACCENT, hover_color="#4A0505",
                      text_color=TEXT_LIGHT, font=FONT_BTN,
                      corner_radius=10, width=130).pack(side="left")

# ─────────────────────────────────────────────
# MODALS
# ─────────────────────────────────────────────

class LeechModal(Modal):
    def __init__(self, parent, on_submit):
        super().__init__(parent, "Open Torrent")
        self.on_submit = on_submit
        ctk.CTkLabel(self, text="Open Torrent", font=("Impact", 22),
                     text_color=ACCENT).pack(anchor="w", padx=24, pady=(16, 2))
        ctk.CTkLabel(self, text="Path to .torrent file",
                     font=FONT_SMALL, text_color=ACCENT).pack(anchor="w", padx=24)
        f = ctk.CTkFrame(self, fg_color="transparent")
        f.pack(fill="x", padx=24, pady=(6, 0))
        self.entry = self._input(f, "/path/to/file.torrent")
        self.entry.bind("<Return>", lambda e: self._ok())
        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(anchor="e", padx=24, pady=8)
        self._buttons(bf, "Download", self._ok)

    def _ok(self):
        p = self.entry.get().strip()
        if p: self.on_submit(p); self.destroy()


class SeedModal(Modal):
    def __init__(self, parent, on_submit):
        super().__init__(parent, "Create Torrent")
        self.on_submit = on_submit
        ctk.CTkLabel(self, text="Create Torrent", font=("Impact", 22),
                     text_color=ACCENT).pack(anchor="w", padx=24, pady=(16, 2))
        ctk.CTkLabel(self, text="Path to file you want to seed",
                     font=FONT_SMALL, text_color=ACCENT).pack(anchor="w", padx=24)
        f = ctk.CTkFrame(self, fg_color="transparent")
        f.pack(fill="x", padx=24, pady=(6, 0))
        self.entry = self._input(f, "/path/to/yourfile.epub")
        self.entry.bind("<Return>", lambda e: self._ok())
        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(anchor="e", padx=24, pady=8)
        self._buttons(bf, "Create & Seed", self._ok)

    def _ok(self):
        p = self.entry.get().strip()
        if p: self.on_submit(p); self.destroy()


class FolderModal(Modal):
    def __init__(self, parent, current, on_submit):
        super().__init__(parent, "Downloads Folder", height=230)
        self.on_submit = on_submit
        ctk.CTkLabel(self, text="Downloads Folder", font=("Impact", 22),
                     text_color=ACCENT).pack(anchor="w", padx=24, pady=(16, 2))
        ctk.CTkLabel(self, text=f"Current: {current}",
                     font=FONT_SMALL, text_color=ACCENT).pack(anchor="w", padx=24)
        f = ctk.CTkFrame(self, fg_color="transparent")
        f.pack(fill="x", padx=24, pady=(6, 0))
        self.entry = self._input(f, "/path/to/downloads")
        self.entry.insert(0, current)
        self.entry.bind("<Return>", lambda e: self._ok())
        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(anchor="e", padx=24, pady=8)
        self._buttons(bf, "Save", self._ok)

    def _ok(self):
        p = self.entry.get().strip()
        if p: self.on_submit(p); self.destroy()

# ─────────────────────────────────────────────
# TOAST
# ─────────────────────────────────────────────

class Toast(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color=ACCENT, corner_radius=50)
        self.label = ctk.CTkLabel(self, text="", font=FONT_BTN, text_color=TEXT_LIGHT)
        self.label.pack(padx=20, pady=8)
        self._job = None

    def show(self, msg, ms=2800):
        self.label.configure(text=msg)
        self.place(relx=0.5, rely=0.95, anchor="s")
        self.lift()
        if self._job: self.after_cancel(self._job)
        self._job = self.after(ms, self.place_forget)

# ─────────────────────────────────────────────
# TABLE ROW
# Uses a single Frame with grid layout.
# Header and rows share identical grid config
# so columns always align.
# ─────────────────────────────────────────────

def _configure_grid(widget):
    """Apply the same column weights to any grid container."""
    for i, (_, min_w, weight) in enumerate(COLUMNS):
        widget.columnconfigure(i, minsize=min_w, weight=weight)


class HeaderRow(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent", height=28)
        self.pack(fill="x", padx=4, pady=(8, 2))
        self.pack_propagate(False)
        _configure_grid(self)
        for i, (name, _, _) in enumerate(COLUMNS):
            ctk.CTkLabel(self, text=name, font=FONT_HEAD,
                         text_color=ACCENT, anchor="w"
                         ).grid(row=0, column=i,
                                padx=(12 if i == 0 else 6, 6),
                                sticky="w")


class TorrentRow(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color=ROW_BG, corner_radius=11, height=44)
        self.pack(fill="x", padx=4, pady=3)
        self.pack_propagate(False)
        _configure_grid(self)

        self.labels = []
        for i in range(len(COLUMNS)):
            lbl = ctk.CTkLabel(self, text="", font=FONT_ROW,
                               text_color=ROW_BG, anchor="w")
            lbl.grid(row=0, column=i,
                     padx=(12 if i == 0 else 6, 6),
                     sticky="w")
            self.labels.append(lbl)

        # Progress bar sits in the Chunks column (index 2)
        self.prog_var = ctk.DoubleVar(value=0)
        self.prog = ctk.CTkProgressBar(self, variable=self.prog_var,
                                       fg_color=ROW_HOVER,
                                       progress_color=ACCENT,
                                       corner_radius=3, height=4)
        # Not placed until needed

    def set_empty(self):
        self.configure(fg_color=ROW_BG)
        for lbl in self.labels:
            lbl.configure(text="", text_color=ROW_BG)
        self.prog.place_forget()

    def update_data(self, data: dict):
        done   = data.get("done_chunks", 0)
        total  = data.get("total_chunks", 1) or 1
        status = data.get("status", "")
        pct    = done / total

        values = [
            data.get("name", ""),
            fmt_size(data.get("size", 0)),
            f"{done}/{total}",
            status,
            str(data.get("seeds",   0)),
            str(data.get("peers",   0)),
            str(data.get("leeches", 0)),
        ]
        for lbl, val in zip(self.labels, values):
            lbl.configure(text=val, text_color=TEXT_BODY)

        # Row color by status
        downloading = status in ("Downloading", "Connecting") or status.startswith("Waiting")
        self.configure(fg_color=ROW_DOWN if downloading else ROW_BG)

        # Progress bar in chunks column
        if downloading and pct < 1.0:
            self.prog_var.set(pct)
            # Place it below the chunks label inside the row
            self.prog.place(relx=0, rely=1.0, anchor="sw",
                            relwidth=1.0 / len(COLUMNS) * 2, x=12, y=-2)
        else:
            self.prog.place_forget()

# ─────────────────────────────────────────────
# MAIN WINDOW
# ─────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self, client):
        super().__init__()
        self.client = client
        self.title("SBITTORRENT")
        self.geometry("920x600")
        self.minsize(760, 480)
        self.configure(fg_color=BG)

        self._build_toolbar()
        self._build_main()
        self.toast = Toast(self)
        self._rows = []
        self._build_rows()
        self._poll()

    # ── Toolbar ───────────────────────────────────────────────────────────────

    def _build_toolbar(self):
        bar = ctk.CTkFrame(self, fg_color=TOOLBAR_BG, corner_radius=0)
        bar.pack(fill="x")
        inner = ctk.CTkFrame(bar, fg_color=TOOLBAR_BG, corner_radius=26)
        inner.pack(fill="x")
        ctk.CTkLabel(inner, text="SBITTORRENT", font=FONT_TITLE,
                     text_color=ACCENT).pack(pady=(14, 4))
        btns = ctk.CTkFrame(inner, fg_color="transparent")
        btns.pack(pady=(0, 12))
        for text, cmd in [
            ("open torrent",            self._open_leech),
            ("change downloads folder", self._open_folder),
            ("create torrent",          self._open_seed),
        ]:
            ctk.CTkButton(btns, text=text, command=cmd,
                          fg_color="transparent", hover_color="#5A5A1A",
                          text_color=ACCENT, font=FONT_BTN,
                          corner_radius=8, border_width=0
                          ).pack(side="left", padx=18)

    # ── Main panel ────────────────────────────────────────────────────────────

    def _build_main(self):
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=22, pady=(14, 6))

        self.panel = ctk.CTkFrame(outer, fg_color=PANEL_BG, corner_radius=22)
        self.panel.pack(fill="both", expand=True)

        # Fixed header (not scrollable)
        HeaderRow(self.panel)

        # Scrollable rows
        self.rows_frame = ctk.CTkScrollableFrame(
            self.panel, fg_color="transparent",
            scrollbar_button_color=ROW_HOVER,
            scrollbar_button_hover_color=ROW_BG
        )
        self.rows_frame.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        self.footer_var = ctk.StringVar(value="starting...")
        ctk.CTkLabel(outer, textvariable=self.footer_var,
                     font=FONT_SMALL, text_color=ACCENT).pack(pady=(4, 0))

    def _build_rows(self):
        self._rows = []
        for _ in range(TOTAL_ROWS):
            row = TorrentRow(self.rows_frame)
            row.set_empty()
            self._rows.append(row)

    # ── Poll ──────────────────────────────────────────────────────────────────

    def _poll(self):
        states = self.client.get_all_states()
        self._render(states)
        self.footer_var.set(
            f"ip: {self.client.my_ip}  •  "
            f"tracker: port {self.client.tracker_url.split(':')[-1].split('/')[0]}  •  "
            f"downloads: {self.client.download_dir}"
        )
        self.after(1000, self._poll)   # poll every second for snappier progress

    def _render(self, states):
        # Add rows if needed
        while len(self._rows) < max(TOTAL_ROWS, len(states)):
            row = TorrentRow(self.rows_frame)
            self._rows.append(row)

        for i, row in enumerate(self._rows):
            if i < len(states):
                row.update_data(states[i])
            else:
                row.set_empty()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _open_leech(self):
        def submit(path):
            if not os.path.exists(path):
                self.toast.show(f"File not found: {os.path.basename(path)}")
                return
            self.client.leech_in_background(path)
            self.toast.show("Download started!")
        LeechModal(self, submit)

    def _open_seed(self):
        def submit(path):
            if not os.path.exists(path):
                self.toast.show(f"File not found: {os.path.basename(path)}")
                return
            def do():
                torrent = self.client.seed_file(path)
                self.client._save_to_kept_files(path)
                self.after(0, lambda: self.toast.show(
                    f"Seeding! Share: {os.path.basename(torrent)}"))
            threading.Thread(target=do, daemon=True).start()
        SeedModal(self, submit)

    def _open_folder(self):
        def submit(path):
            self.client.set_download_dir(path)
            self.toast.show("Downloads folder updated!")
        FolderModal(self, self.client.download_dir, submit)


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    backend_dir  = os.path.join(project_root, "backend")
    sys.path.insert(0, backend_dir)

    from torrent import create_torrent
    from client import Client, TRACKER_PORT, KEPT_FILES

    kept_files_path = os.path.join(backend_dir, "kept_files.txt")

    # Auto-detect IP
    my_ip = get_local_ip()
    print(f"[GUI] Using IP: {my_ip}")

    client     = Client(my_ip)
    seed_files = []

    # Auto-load kept_files.txt
    if os.path.exists(kept_files_path):
        with open(kept_files_path) as f:
            for line in f:
                line = line.strip()
                if line and os.path.exists(line):
                    seed_files.append(line)
                elif line:
                    print(f"[GUI] Skipping missing file: {line}")

    seed_files = list(dict.fromkeys(os.path.abspath(p) for p in seed_files if os.path.exists(p)))

    seed_pairs = []
    for fp in seed_files:
        tp = fp + ".torrent"
        if os.path.exists(tp):
            print(f"[GUI] Reusing torrent: {os.path.basename(tp)}")
        else:
            create_torrent(fp, f"http://{my_ip}:{TRACKER_PORT}/announce", tp)
        seed_pairs.append((tp, fp))

    client.start(seed_pairs=seed_pairs)

    app = App(client)
    app.mainloop()
    client.multi_tracker.stop_all()