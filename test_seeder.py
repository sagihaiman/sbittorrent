import os
import sys
import time
import threading
from torrent import create_torrent, load_torrent
from tracker import run_tracker
from tracker_client import MultiTrackerClient
from protocol import build_seeder_library, run_seeder

TRACKER_PORT = 8000
SEEDER_PORT  = 9000

# ─────────────────────────────────────────────
# ARGS
# Usage: python test_seeder.py <your_ip> <file1> [file2] [file3] ...
# ─────────────────────────────────────────────

if len(sys.argv) < 2:
    print("Usage: python test_seeder.py <your_ip> <file1> [file2] ...")
    print("  your_ip: IP address other machines can reach you on")
    print("  file1+:  files to seed")
    sys.exit(1)

my_ip      = sys.argv[1]
file_paths = []
with open("kept_files.txt") as f:
    for line in f:
        file_paths.append(line.strip())
file_paths += sys.argv[2:]
tracker_url = f"http://{my_ip}:{TRACKER_PORT}/announce"

# Validate files
for fp in file_paths:
    if not os.path.exists(fp):
        print(f"[SEEDER] File not found: {fp}")
        sys.exit(1)

# ── Step 1: Start tracker ─────────────────────────────────────────────────────
print("\n── Step 1: Starting tracker ─────────────────────────")
tracker_thread = threading.Thread(
    target=run_tracker,
    kwargs={"host": "0.0.0.0", "port": TRACKER_PORT},
    daemon=True
)
tracker_thread.start()
time.sleep(0.3)
print(f"[SEEDER] Tracker running at {tracker_url}")

# ── Step 2: Create .torrent files ─────────────────────────────────────────────
print("\n── Step 2: Creating .torrent files ──────────────────")
torrent_file_pairs = {}  # (torrent_path, file_path)

for file_path in file_paths:
    torrent_path = file_path + ".torrent"
    create_torrent(file_path, tracker_url, torrent_path)
    torrent_file_pairs[torrent_path] = file_path
    print(f"[SEEDER] Share '{torrent_path}' with leechers")

# ── Step 3: Announce all torrents to tracker ──────────────────────────────────
print("\n── Step 3: Announcing to tracker ────────────────────")
multi_client = MultiTrackerClient(local_port=SEEDER_PORT)

for torrent_path, file_path in torrent_file_pairs.items():
    file_size = os.path.getsize(file_path)
    multi_client.add_torrent(torrent_path, uploaded=file_size, left=0)

multi_client.start_all()
multi_client.list_torrents()

# ── Step 4: Build library and serve ──────────────────────────────────────────
print("\n── Step 4: Building library and serving ─────────────")
library = build_seeder_library(torrent_file_pairs)

print(f"\n[SEEDER] Serving {len(library)} file(s) on {my_ip}:{SEEDER_PORT}")
print(f"[SEEDER] Press Ctrl+C to stop\n")

# run_seeder blocks in main thread — keeps script alive
run_seeder(library=library, host="0.0.0.0", port=SEEDER_PORT)