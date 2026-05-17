import threading
import os
import time
import sys
from protocol import run_seeder, run_leecher, file_sha1

# ── Config ────────────────────────────────────────────────────────────────────
TEST_FILE     = sys.argv[1] if len(sys.argv) > 1 else "test_input.epub"
RECEIVED_FILE = "received_" + os.path.basename(TEST_FILE)
SEEDER_PORT   = 9000
LEECH_PORT    = 9001

# ── Validate ──────────────────────────────────────────────────────────────────
if not os.path.exists(TEST_FILE):
    print(f"[TEST] ❌ File not found: {TEST_FILE}")
    sys.exit(1)

# ── File info ─────────────────────────────────────────────────────────────────
fhash      = file_sha1(TEST_FILE)
file_size  = os.path.getsize(TEST_FILE)
num_chunks = (file_size + 16 * 1024 - 1) // (16 * 1024)

print(f"[TEST] File:   {TEST_FILE} ({file_size} bytes)")
print(f"[TEST] Hash:   {fhash.hex()}")
print(f"[TEST] Chunks: {num_chunks}")

# ── Seeder in background thread ───────────────────────────────────────────────
def seeder_thread():
    run_seeder(TEST_FILE, host="127.0.0.1", port=SEEDER_PORT)

t = threading.Thread(target=seeder_thread, daemon=True)
t.start()
time.sleep(0.5)  # give seeder time to bind

# ── Leecher in main thread ────────────────────────────────────────────────────
run_leecher(
    file_hash=fhash,
    num_expected_chunks=num_chunks,
    out_path=RECEIVED_FILE,
    seeder_host="127.0.0.1",
    seeder_port=SEEDER_PORT,
    local_port=LEECH_PORT,
)

# ── Verify ────────────────────────────────────────────────────────────────────
if os.path.exists(RECEIVED_FILE):
    if file_sha1(TEST_FILE) == file_sha1(RECEIVED_FILE):
        print(f"\n[TEST] ✅ SUCCESS — file saved to {RECEIVED_FILE}")
    else:
        print(f"\n[TEST] ❌ FAIL — hashes don't match")
else:
    print(f"\n[TEST] ❌ FAIL — output file not created")