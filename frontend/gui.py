import customtkinter as ctk
import threading
import os
import sys

# ── Theme ─────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

BG          = "#C8922A"
TOOLBAR_BG  = "#8B8B2A"
PANEL_BG    = "#9B5E1A"
ROW_BG      = "#7A4010"
ROW_HOVER   = "#6B3508"
ROW_DOWN    = "#7A3A00"
ACCENT      = "#6B0A0A"
TEXT_LIGHT  = "#C8922A"
TEXT_BODY   = "#1A0A00"
WHITE       = "#F5E6C8"

FONT_TITLE  = ("Impact", 42, "bold")
FONT_BTN    = ("Arial Rounded MT Bold", 14, "bold")
FONT_HEAD   = ("Arial Rounded MT Bold", 13, "bold")
FONT_ROW    = ("Arial", 13, "bold")
FONT_SMALL  = ("Arial", 11)

COL_WIDTHS  = [220, 80, 90, 120, 60, 60, 70]
COL_NAMES   = ["Name", "Size", "Chunks", "Status", "Seeds", "Peers", "Leeches"]
TOTAL_ROWS  = 8

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def fmt_size(b):
    if b >= 1073741824: return f"{b/1073741824:.1f} GB"
    if b >= 1048576:    return f"{round(b/1048576)} MB"
    if b >= 1024:       return f"{round(b/1024)} KB"
    return f"{b} B"

# ─────────────────────────────────────────────
# MODAL BASE
# ─────────────────────────────────────────────

class Modal(ctk.CTkToplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.title(title)
        self.configure(fg_color=PANEL_BG)
        self.resizable(False, False)
        self.grab_set()
        self.lift()
        self.focus_force()
        # Center on parent
        self.update_idletasks()
        px = parent.winfo_x() + parent.winfo_width()  // 2
        py = parent.winfo_y() + parent.winfo_height() // 2
        w, h = 420, 200
        self.geometry(f"{w}x{h}+{px - w//2}+{py - h//2}")

    def _buttons(self, frame, ok_text, ok_cmd):
        ctk.CTkButton(frame, text="Cancel", command=self.destroy,
                      fg_color=ROW_HOVER, hover_color=ROW_BG,
                      text_color=TEXT_LIGHT, font=FONT_BTN,
                      corner_radius=10, width=100).pack(side="left", padx=(0,10))
        ctk.CTkButton(frame, text=ok_text, command=ok_cmd,
                      fg_color=ACCENT, hover_color="#4A0505",
                      text_color=TEXT_LIGHT, font=FONT_BTN,
                      corner_radius=10, width=120).pack(side="left")

    def _input(self, parent, placeholder):
        e = ctk.CTkEntry(parent, placeholder_text=placeholder,
                         fg_color=ROW_BG, border_color=ROW_HOVER,
                         text_color=WHITE, placeholder_text_color="#9B6030",
                         font=FONT_ROW, corner_radius=10, height=38)
        e.pack(fill="x", pady=(0, 6))
        return e

# ─────────────────────────────────────────────
# MODALS
# ─────────────────────────────────────────────

class LeechModal(Modal):
    def __init__(self, parent, on_submit):
        super().__init__(parent, "Open Torrent")
        self.on_submit = on_submit
        pad = {"padx": 24, "pady": 8}

        ctk.CTkLabel(self, text="Open Torrent", font=("Impact", 22),
                     text_color=ACCENT).pack(anchor="w", **pad)
        ctk.CTkLabel(self, text="Path to .torrent file", font=FONT_SMALL,
                     text_color=ACCENT).pack(anchor="w", padx=24, pady=(0,2))

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="x", padx=24)
        self.entry = self._input(inner, "/path/to/file.torrent")
        self.entry.bind("<Return>", lambda e: self._ok())

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(anchor="e", padx=24, pady=10)
        self._buttons(btns, "Download", self._ok)

    def _ok(self):
        path = self.entry.get().strip()
        if path:
            self.on_submit(path)
            self.destroy()


class SeedModal(Modal):
    def __init__(self, parent, on_submit):
        super().__init__(parent, "Create Torrent")
        self.on_submit = on_submit
        pad = {"padx": 24, "pady": 8}

        ctk.CTkLabel(self, text="Create Torrent", font=("Impact", 22),
                     text_color=ACCENT).pack(anchor="w", **pad)
        ctk.CTkLabel(self, text="Path to file you want to seed", font=FONT_SMALL,
                     text_color=ACCENT).pack(anchor="w", padx=24, pady=(0,2))

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="x", padx=24)
        self.entry = self._input(inner, "/path/to/yourfile.epub")
        self.entry.bind("<Return>", lambda e: self._ok())

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(anchor="e", padx=24, pady=10)
        self._buttons(btns, "Create & Seed", self._ok)

    def _ok(self):
        path = self.entry.get().strip()
        if path:
            self.on_submit(path)
            self.destroy()


class FolderModal(Modal):
    def __init__(self, parent, current, on_submit):
        super().__init__(parent, "Downloads Folder")
        self.on_submit = on_submit
        pad = {"padx": 24, "pady": 8}

        ctk.CTkLabel(self, text="Downloads Folder", font=("Impact", 22),
                     text_color=ACCENT).pack(anchor="w", **pad)
        ctk.CTkLabel(self, text=f"Current: {current}", font=FONT_SMALL,
                     text_color=ACCENT).pack(anchor="w", padx=24, pady=(0,2))

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="x", padx=24)
        self.entry = self._input(inner, "/path/to/downloads")
        self.entry.insert(0, current)
        self.entry.bind("<Return>", lambda e: self._ok())

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(anchor="e", padx=24, pady=10)
        self._buttons(btns, "Save", self._ok)

    def _ok(self):
        path = self.entry.get().strip()
        if path:
            self.on_submit(path)
            self.destroy()

# ─────────────────────────────────────────────
# TOAST
# ─────────────────────────────────────────────

class Toast(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color=ACCENT, corner_radius=50)
        self.label = ctk.CTkLabel(self, text="", font=FONT_BTN,
                                  text_color=TEXT_LIGHT)
        self.label.pack(padx=20, pady=8)
        self._job = None

    def show(self, msg, ms=2800):
        self.label.configure(text=msg)
        self.place(relx=0.5, rely=0.95, anchor="s")
        self.lift()
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(ms, self.place_forget)

# ─────────────────────────────────────────────
# ROW WIDGET
# ─────────────────────────────────────────────

class TorrentRow(ctk.CTkFrame):
    def __init__(self, parent, empty=False):
        super().__init__(parent, fg_color=ROW_BG, corner_radius=11,
                         height=42)
        self.pack(fill="x", pady=3)
        self.pack_propagate(False)

        self.labels = []
        for i, w in enumerate(COL_WIDTHS):
            lbl = ctk.CTkLabel(self, text="", font=FONT_ROW,
                               text_color=TEXT_BODY, width=w,
                               anchor="w")
            lbl.grid(row=0, column=i, padx=(10 if i==0 else 4, 4), pady=0, sticky="w")
            self.labels.append(lbl)

        self.columnconfigure(0, weight=1)

        # Progress bar (hidden by default, shown over Chunks label)
        self.prog_var = ctk.DoubleVar(value=0)
        self.prog     = ctk.CTkProgressBar(self, variable=self.prog_var,
                                           fg_color=ROW_HOVER,
                                           progress_color=ACCENT,
                                           corner_radius=3, height=4, width=80)
        if empty:
            self.configure(fg_color=ROW_BG)
            for lbl in self.labels:
                lbl.configure(text_color=ROW_BG)

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
            # Truncate long names
            if len(val) > 28 and lbl == self.labels[0]:
                val = val[:25] + "..."
            lbl.configure(text=val, text_color=TEXT_BODY)

        # Color row by status
        if status in ("Downloading", "Connecting") or status.startswith("Waiting"):
            self.configure(fg_color=ROW_DOWN)
        else:
            self.configure(fg_color=ROW_BG)

        # Show progress bar under chunks column
        if pct < 1.0 and status == "Downloading":
            self.prog_var.set(pct)
            self.prog.place(x=sum(COL_WIDTHS[:2]) + 16, y=30)
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
        self.geometry("900x620")
        self.minsize(800, 500)
        self.configure(fg_color=BG)
        self.resizable(True, True)

        self._build_toolbar()
        self._build_main()

        self.toast  = Toast(self)
        self._rows  = []
        self._build_rows()

        # Start polling
        self._poll()

    # ── Toolbar ────────────────────────────────────────────────────────────────

    def _build_toolbar(self):
        self.toolbar = ctk.CTkFrame(self, fg_color=TOOLBAR_BG,
                                    corner_radius=0)
        self.toolbar.pack(fill="x")

        # Round bottom corners via inner padding
        inner = ctk.CTkFrame(self.toolbar, fg_color=TOOLBAR_BG, corner_radius=28)
        inner.pack(fill="x", padx=0, pady=(0, 0))

        ctk.CTkLabel(inner, text="SBITTORRENT", font=FONT_TITLE,
                     text_color=ACCENT).pack(pady=(14, 4))

        btns = ctk.CTkFrame(inner, fg_color="transparent")
        btns.pack(pady=(0, 12))

        for text, cmd in [
            ("open torrent",          self._open_leech),
            ("change downloads folder", self._open_folder),
            ("create torrent",        self._open_seed),
        ]:
            ctk.CTkButton(btns, text=text, command=cmd,
                          fg_color="transparent", hover_color=f"#5A5A1A",
                          text_color=ACCENT, font=FONT_BTN,
                          corner_radius=8, border_width=0).pack(side="left", padx=18)

    # ── Main panel ─────────────────────────────────────────────────────────────

    def _build_main(self):
        self.main = ctk.CTkFrame(self, fg_color="transparent")
        self.main.pack(fill="both", expand=True, padx=24, pady=(16, 8))

        self.panel = ctk.CTkFrame(self.main, fg_color=PANEL_BG, corner_radius=22)
        self.panel.pack(fill="both", expand=True)

        # Header row
        hdr = ctk.CTkFrame(self.panel, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(12, 4))

        for i, (name, w) in enumerate(zip(COL_NAMES, COL_WIDTHS)):
            ctk.CTkLabel(hdr, text=name, font=FONT_HEAD,
                         text_color=ACCENT, width=w, anchor="w"
                         ).grid(row=0, column=i, padx=(10 if i==0 else 4, 4), sticky="w")

        # Scrollable rows container
        self.rows_frame = ctk.CTkScrollableFrame(self.panel, fg_color="transparent",
                                                  scrollbar_button_color=ROW_HOVER,
                                                  scrollbar_button_hover_color=ROW_BG)
        self.rows_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Footer
        self.footer_var = ctk.StringVar(value="connecting...")
        ctk.CTkLabel(self.main, textvariable=self.footer_var,
                     font=FONT_SMALL, text_color=ACCENT
                     ).pack(pady=(6, 0))

    def _build_rows(self):
        for widget in self.rows_frame.winfo_children():
            widget.destroy()
        self._rows = []
        for _ in range(TOTAL_ROWS):
            row = TorrentRow(self.rows_frame, empty=True)
            self._rows.append(row)

    # ── Poll client state ──────────────────────────────────────────────────────

    def _poll(self):
        states = self.client.get_all_states()
        self._render(states)
        self.footer_var.set(
            f"your ip: {self.client.my_ip}  •  "
            f"tracker: {self.client.tracker_url}  •  "
            f"downloads: {self.client.download_dir}"
        )
        self.after(2000, self._poll)

    def _render(self, states: list):
        # Grow rows list if needed
        while len(self._rows) < max(TOTAL_ROWS, len(states)):
            self._rows.append(TorrentRow(self.rows_frame))

        for i, row in enumerate(self._rows):
            if i < len(states):
                row.configure(fg_color=ROW_BG)
                for lbl in row.labels:
                    lbl.configure(text_color=TEXT_BODY)
                row.update_data(states[i])
                row.pack(fill="x", pady=3)
            else:
                # Empty placeholder
                row.configure(fg_color=ROW_BG)
                for lbl in row.labels:
                    lbl.configure(text="", text_color=ROW_BG)
                row.prog.place_forget()
                row.pack(fill="x", pady=3)

    # ── Toolbar actions ────────────────────────────────────────────────────────

    def _open_leech(self):
        def submit(path):
            if not os.path.exists(path):
                self.toast.show(f"File not found: {path}")
                return
            self.client.leech_in_background(path)
            self.toast.show("Download started!")
        LeechModal(self, submit)

    def _open_seed(self):
        def submit(path):
            if not os.path.exists(path):
                self.toast.show(f"File not found: {path}")
                return
            def do():
                torrent = self.client.seed_file(path)
                self.client._save_to_kept_files(path)
                self.after(0, lambda: self.toast.show(f"Seeding! Torrent: {os.path.basename(torrent)}"))
            threading.Thread(target=do, daemon=True).start()
        SeedModal(self, submit)

    def _open_folder(self):
        def submit(path):
            self.client.set_download_dir(path)
            self.toast.show(f"Downloads folder updated!")
        FolderModal(self, self.client.download_dir, submit)


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # Add project root to path so imports work
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from backend.torrent import create_torrent
    from client import Client, TRACKER_PORT, KEPT_FILES

    if len(sys.argv) < 2:
        print("Usage: python gui.py <your_ip> [file_to_seed ...]")
        sys.exit(1)

    my_ip      = sys.argv[1]
    seed_files = list(sys.argv[2:])
    client     = Client(my_ip)

    # Auto-load kept_files.txt
    if os.path.exists(KEPT_FILES):
        with open(KEPT_FILES) as f:
            for line in f:
                line = line.strip()
                if line and os.path.exists(line):
                    seed_files.append(line)
                elif line:
                    print(f"[GUI] kept_files.txt: skipping missing: {line}")

    # Deduplicate
    seed_files = list(dict.fromkeys(os.path.abspath(p) for p in seed_files if os.path.exists(p)))

    # Build seed pairs
    seed_pairs = []
    for fp in seed_files:
        tp = fp + ".torrent"
        if os.path.exists(tp):
            print(f"[GUI] Reusing torrent: {tp}")
        else:
            create_torrent(fp, f"http://{my_ip}:{TRACKER_PORT}/announce", tp)
        seed_pairs.append((tp, fp))

    # Start engine in background
    client.start(seed_pairs=seed_pairs)

    # Launch GUI (blocks until window closed)
    app = App(client)
    app.mainloop()

    # Cleanup
    client.multi_tracker.stop_all()