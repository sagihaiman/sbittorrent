import os
import sys
import time
import threading
from torrent_files.torrent import create_torrent, load_torrent
from torrent_files.tracker import run_tracker
from torrent_files.tracker_client import TrackerClient
from Handshake.protocol import run_seeder, file_sha1

TRACKER_PORT = 8000
SEEDER_PORT  = 9000

# ── Args ──────────────────────────────────────────────────────────────────────
if len(sys.argv) < 3:
    print("Usage: python test_seeder.py <file> <your_ip>")
    print("  your_ip: the IP address other machines can reach you on")
    sys.exit(1)

file_path   = sys.argv[1]
my_ip       = sys.argv[2]
torrent_path = file_path + ".torrent"
tracker_url  = f"http://{my_ip}:{TRACKER_PORT}/announce"

if not os.path.exists(file_path):
    print(f"[SEEDER] ❌ File not found: {file_path}")
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

# ── Step 2: Create .torrent file ──────────────────────────────────────────────
print("\n── Step 2: Creating .torrent file ───────────────────")
create_torrent(file_path, tracker_url, torrent_path)
_, info_hash = load_torrent(torrent_path)
print(f"[SEEDER] Share '{torrent_path}' with the leecher")

# ── Step 3: Announce to tracker + serve file ──────────────────────────────────
print("\n── Step 3: Announcing to tracker and serving ────────")

seeder_client = TrackerClient(torrent_path, local_port=SEEDER_PORT)
seeder_client.uploaded = os.path.getsize(file_path)
seeder_client.left     = 0  # we have the full file
seeder_client.start()

print(f"[SEEDER] Serving on {my_ip}:{SEEDER_PORT} — waiting for leechers...")
print(f"[SEEDER] Press Ctrl+C to stop\n")

# Run seeder in main thread so the script stays alive
run_seeder(file_path, host="0.0.0.0", port=SEEDER_PORT, file_hash=info_hash)