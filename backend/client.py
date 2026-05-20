import os
import sys
import time
import threading
from torrent import create_torrent, load_torrent
from tracker import run_tracker
from tracker_client import MultiTrackerClient
from protocol import run_seeder, run_leecher, file_sha1, split_file

TRACKER_PORT = 8000
SEEDER_PORT  = 9000
LEECH_PORT   = 9001

# Always resolve paths relative to client.py (backend/) regardless of cwd
_HERE        = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "Torrents")
KEPT_FILES   = os.path.join(_HERE, "kept_files.txt")

# ─────────────────────────────────────────────
# CLIENT
# ─────────────────────────────────────────────

class Client:
    def __init__(self, my_ip: str):
        self.my_ip              = my_ip
        self.tracker_url        = f"http://{my_ip}:{TRACKER_PORT}/announce"
        self.library            = {}   # info_hash -> entry, shared with seeder thread
        self.library_lock       = threading.Lock()
        self.multi_tracker      = MultiTrackerClient(local_port=SEEDER_PORT)
        self.leech_port_counter = LEECH_PORT
        self.leech_lock         = threading.Lock()
        self.download_dir       = os.path.abspath(DOWNLOAD_DIR)

        # Torrent state for GUI: info_hash_hex -> state dict
        self.torrent_states     = {}
        self.states_lock        = threading.Lock()

        os.makedirs(self.download_dir, exist_ok=True)

    # ── Internal: next available leech port ───────────────────────────────────

    def _next_leech_port(self) -> int:
        with self.leech_lock:
            port = self.leech_port_counter
            self.leech_port_counter += 10
            return port

    # ── Torrent state management ──────────────────────────────────────────────

    def _set_state(self, info_hash_hex: str, **kwargs):
        with self.states_lock:
            if info_hash_hex not in self.torrent_states:
                self.torrent_states[info_hash_hex] = {}
            self.torrent_states[info_hash_hex].update(kwargs)

    def get_all_states(self) -> list:
        with self.states_lock:
            return list(self.torrent_states.values())

    # ── Start tracker + seeder ────────────────────────────────────────────────

    def start(self, seed_pairs: list = None):
        # Tracker
        threading.Thread(
            target=run_tracker,
            kwargs={"host": "0.0.0.0", "port": TRACKER_PORT},
            daemon=True
        ).start()
        time.sleep(0.3)

        # Pre-seed files
        if seed_pairs:
            for torrent_path, file_path in seed_pairs:
                self._add_to_library(torrent_path, file_path)
            self.multi_tracker.start_all()

        # Seeder thread
        threading.Thread(
            target=run_seeder,
            kwargs={"library": self.library, "host": "0.0.0.0", "port": SEEDER_PORT},
            daemon=True
        ).start()

        print(f"[CLIENT] Started | tracker={self.tracker_url} | seeder port={SEEDER_PORT}")

    # ── Add a file to the seeder library ──────────────────────────────────────

    def _add_to_library(self, torrent_path: str, file_path: str):
        torrent, info_hash = load_torrent(torrent_path)
        chunks        = split_file(file_path)
        fhash         = file_sha1(file_path)
        info_hash_hex = info_hash.hex()
        file_size     = os.path.getsize(file_path)
        num_chunks    = len(chunks)

        with self.library_lock:
            self.library[info_hash] = {
                "file_path": file_path,
                "chunks":    chunks,
                "file_hash": fhash,
            }

        # Announce as seeder
        if info_hash_hex not in self.multi_tracker._clients:
            self.multi_tracker.add_torrent(torrent_path, uploaded=file_size, left=0)
            self.multi_tracker._clients[info_hash_hex].start()
        else:
            c = self.multi_tracker._clients[info_hash_hex]
            c.uploaded = file_size
            c.left     = 0
            c.announce("completed")

        # Update GUI state
        self._set_state(info_hash_hex,
            name         = os.path.basename(file_path),
            size         = file_size,
            done_chunks  = num_chunks,
            total_chunks = num_chunks,
            status       = "Seeding",
            info_hash    = info_hash_hex,
            torrent_path = torrent_path,
        )
        self._refresh_peers(info_hash_hex)

    # ── Refresh peer counts from tracker ──────────────────────────────────────

    def _refresh_peers(self, info_hash_hex: str):
        """Update seeds/peers/leeches counts from tracker data."""
        try:
            client  = self.multi_tracker._clients.get(info_hash_hex)
            if not client:
                return
            peers   = client.get_peers()
            # Count seeders (left==0) vs leechers among known peers
            # Tracker response gives us complete/incomplete counts
            # We approximate from what we have
            self._set_state(info_hash_hex,
                seeds   = 1,   # at minimum we're seeding
                peers   = len(peers),
                leeches = 0,
            )
        except Exception:
            pass

    # ── Seed a new file ────────────────────────────────────────────────────────

    def seed_file(self, file_path: str) -> str:
        file_path    = os.path.abspath(file_path)
        torrent_path = file_path + ".torrent"
        if os.path.exists(torrent_path):
            print(f"[CLIENT] Reusing existing torrent: {torrent_path}")
        else:
            create_torrent(file_path, self.tracker_url, torrent_path)
        self._add_to_library(torrent_path, file_path)
        return torrent_path

    # ── Leech a torrent ────────────────────────────────────────────────────────

    def leech(self, torrent_path: str):
        torrent_path       = os.path.abspath(torrent_path)
        torrent, info_hash = load_torrent(torrent_path)
        file_name          = torrent[b"info"][b"name"].decode()
        file_size          = torrent[b"info"][b"length"]
        num_chunks         = (file_size + 8 * 1024 - 1) // (8 * 1024)
        out_path           = os.path.abspath(os.path.join(self.download_dir, file_name))
        info_hash_hex      = info_hash.hex()

        print(f"[LEECHER] Downloading: {file_name} ({file_size} bytes)")

        # Initial GUI state
        self._set_state(info_hash_hex,
            name         = file_name,
            size         = file_size,
            done_chunks  = 0,
            total_chunks = num_chunks,
            status       = "Connecting",
            seeds        = 0,
            peers        = 0,
            leeches      = 0,
            info_hash    = info_hash_hex,
            torrent_path = torrent_path,
        )

        # Announce as leecher
        if info_hash_hex not in self.multi_tracker._clients:
            self.multi_tracker.add_torrent(torrent_path, uploaded=0, left=file_size)
            self.multi_tracker._clients[info_hash_hex].announce("started")

        # Retry peer discovery
        peers = []
        for attempt in range(10):
            peers = self.multi_tracker.get_peers(info_hash_hex)
            if peers:
                break
            print(f"[LEECHER] Waiting for peers... ({attempt+1}/10)")
            self._set_state(info_hash_hex, status=f"Waiting for peers ({attempt+1}/10)")
            time.sleep(2)

        if not peers:
            print(f"[LEECHER] No peers found for {file_name}")
            self._set_state(info_hash_hex, status="No peers found")
            return

        self._set_state(info_hash_hex,
            status = "Downloading",
            seeds  = len(peers),
            peers  = len(peers),
        )

        # Shared results dict — passed into run_leecher so we can track progress
        shared_results      = {}
        shared_results_lock = threading.Lock()

        def progress_tracker():
            while True:
                with shared_results_lock:
                    done = len(shared_results)
                self._set_state(info_hash_hex, done_chunks=done)
                if done >= num_chunks:
                    break
                time.sleep(0.3)

        threading.Thread(target=progress_tracker, daemon=True).start()

        local_port = self._next_leech_port()
        try:
            run_leecher(
                file_hash=info_hash,
                num_expected_chunks=num_chunks,
                out_path=out_path,
                peers=peers,
                local_port=local_port,
                shared_results=shared_results,
                shared_results_lock=shared_results_lock,
            )
        except RuntimeError as e:
            print(f"[LEECHER] Download failed: {e}")
            self._set_state(info_hash_hex, status="Failed")
            return

        # Only mark as seeding if file actually exists
        if not os.path.exists(out_path):
            self._set_state(info_hash_hex, status="Failed")
            return

        print(f"[LEECHER] Finished: {file_name} → {out_path}")
        self._save_to_kept_files(out_path)
        self._add_to_library(torrent_path, out_path)  # sets status to Seeding

    def leech_in_background(self, torrent_path: str):
        threading.Thread(target=self.leech, args=(torrent_path,), daemon=True).start()

    # ── kept_files.txt ────────────────────────────────────────────────────────

    def _save_to_kept_files(self, file_path: str):
        abs_path = os.path.abspath(file_path)
        existing = set()
        if os.path.exists(KEPT_FILES):
            with open(KEPT_FILES) as f:
                existing = {line.strip() for line in f if line.strip()}
        if abs_path not in existing:
            with open(KEPT_FILES, "a") as f:
                f.write(abs_path + "\n")

    def set_download_dir(self, path: str):
        self.download_dir = os.path.abspath(path)
        os.makedirs(self.download_dir, exist_ok=True)
        print(f"[CLIENT] Download dir: {self.download_dir}")