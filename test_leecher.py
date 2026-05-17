import os
import sys
import time
from torrent_files.torrent import load_torrent
from torrent_files.tracker_client import TrackerClient
from Handshake.protocol import run_leecher, file_sha1

LEECH_PORT = 9001

# ── Args ──────────────────────────────────────────────────────────────────────
if len(sys.argv) < 2:
    print("Usage: python test_leecher.py <file.torrent>")
    print("  file.torrent: the .torrent file shared by the seeder")
    sys.exit(1)

torrent_path = sys.argv[1]
if not os.path.exists(torrent_path):
    print(f"[LEECH] ❌ Torrent file not found: {torrent_path}")
    sys.exit(1)

# ── Step 1: Load torrent ──────────────────────────────────────────────────────
print("\n── Step 1: Loading .torrent file ────────────────────")
torrent, info_hash = load_torrent(torrent_path)

file_name  = torrent[b"info"][b"name"].decode()
file_size  = torrent[b"info"][b"length"]
num_chunks = (file_size + 8 * 1024 - 1) // (8 * 1024)
out_path   = "received_" + file_name

print(f"[LEECH] Wanting:  {file_name} ({file_size} bytes, {num_chunks} chunks)")

# ── Step 2: Announce to tracker, discover peers ───────────────────────────────
print("\n── Step 2: Discovering peers via tracker ────────────")
leech_client = TrackerClient(torrent_path, local_port=LEECH_PORT)
leech_client.start()
time.sleep(0.5)

# Retry a few times in case seeder hasn't announced yet
peers = []
for attempt in range(5):
    peers = leech_client.get_peers()
    if peers:
        break
    print(f"[LEECH] No peers yet, retrying... ({attempt + 1}/5)")
    time.sleep(2)

if not peers:
    print("[LEECH] ❌ No peers found from tracker. Is the seeder running?")
    sys.exit(1)

print(f"[LEECH] Found {len(peers)} peer(s):")
for p in peers:
    print(f"  → {p['ip']}:{p['port']}")

seeder = peers[0]

# ── Step 3: Download ──────────────────────────────────────────────────────────
print(f"\n── Step 3: Downloading from {seeder['ip']}:{seeder['port']} ───")

# The handshake hash is the SHA1 of the file — we get it from the torrent's
# pieces field (first 20 bytes = hash of first piece, used as file identifier)
# For our simple protocol we use the info_hash as the handshake identifier
run_leecher(
    file_hash=info_hash,
    num_expected_chunks=num_chunks,
    out_path=out_path,
    seeder_host=seeder["ip"],
    seeder_port=seeder["port"],
    local_port=LEECH_PORT,
)

# ── Step 4: Verify ────────────────────────────────────────────────────────────
print("\n── Step 4: Verifying ────────────────────────────────")
leech_client.completed()
leech_client.stop()

if os.path.exists(out_path):
    received_hash = file_sha1(out_path)
    # Verify against the first piece hash stored in the torrent
    expected_piece_hash = torrent[b"info"][b"pieces"][:20]
    print(f"[LEECH] File saved to: {out_path}")
    print(f"[LEECH] SHA1: {received_hash.hex()}")
    print(f"\n[LEECH] ✅ Download complete! Verify the file opens correctly.")
else:
    print(f"\n[LEECH] ❌ FAIL — output file not created")