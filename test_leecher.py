import os
import sys
import time
from torrent import load_torrent
from tracker_client import TrackerClient
from protocol import run_leecher

LEECH_PORT = 9001

if len(sys.argv) < 2:
    print("Usage: python test_leecher.py <file.torrent>")
    sys.exit(1)

torrent_path = sys.argv[1]
if not os.path.exists(torrent_path):
    print(f"[LEECH] File not found: {torrent_path}")
    sys.exit(1)

# ── Step 1: Load torrent ──────────────────────────────────────────────────────
print("\n── Step 1: Loading .torrent file ────────────────────")
torrent, info_hash = load_torrent(torrent_path)

file_name  = torrent[b"info"][b"name"].decode()
file_size  = torrent[b"info"][b"length"]
num_chunks = (file_size + 8 * 1024 - 1) // (8 * 1024)
out_path   = "received_" + file_name

print(f"[LEECH] Wanting: {file_name} ({file_size} bytes, {num_chunks} chunks)")

# ── Step 2: Discover peers via all trackers ───────────────────────────────────
print("\n── Step 2: Discovering peers via tracker(s) ─────────")
leech_client = TrackerClient(torrent_path, local_port=LEECH_PORT)
leech_client.start()
time.sleep(0.5)

peers = []
for attempt in range(5):
    peers = leech_client.get_peers()
    if peers:
        break
    print(f"[LEECH] No peers yet, retrying... ({attempt+1}/5)")
    time.sleep(2)

if not peers:
    print("[LEECH] No peers found. Is the seeder running?")
    sys.exit(1)

print(f"[LEECH] Found {len(peers)} peer(s):")
for p in peers:
    print(f"  -> {p['ip']}:{p['port']}")

# ── Step 3: Download in parallel ─────────────────────────────────────────────
print(f"\n── Step 3: Downloading from {len(peers)} peer(s) in parallel ──")
run_leecher(
    file_hash=info_hash,
    num_expected_chunks=num_chunks,
    out_path=out_path,
    peers=peers,
    local_port=LEECH_PORT,
)

# ── Step 4: Announce completion ───────────────────────────────────────────────
print("\n── Step 4: Announcing completion ────────────────────")
leech_client.completed()

print(f"[LEECH] Done! File saved to: {out_path}")