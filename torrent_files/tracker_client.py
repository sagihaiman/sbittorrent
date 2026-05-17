import os
import time
import hashlib
import threading
import urllib.request
import urllib.parse
from torrent_files.torrent import bdecode, load_torrent

# ─────────────────────────────────────────────
# PEER ID
# ─────────────────────────────────────────────

def make_peer_id() -> bytes:
    """Generate a 20-byte peer ID in Azureus style: -XX0001-<random12bytes>"""
    prefix = b"-OT0001-"  # OT = OurTorrent
    random_part = os.urandom(12)
    return prefix + random_part


# ─────────────────────────────────────────────
# TRACKER CLIENT
# ─────────────────────────────────────────────

class TrackerClient:
    def __init__(self, torrent_path: str, local_port: int, peer_id: bytes = None):
        self.torrent, self.info_hash = load_torrent(torrent_path)
        self.local_port  = local_port
        self.peer_id     = peer_id or make_peer_id()
        self.tracker_url = self.torrent[b"announce"].decode()
        self.downloaded  = 0
        self.uploaded    = 0
        self.left        = self.torrent[b"info"][b"length"]
        self._stop       = threading.Event()
        self._peers      = []
        self._lock       = threading.Lock()

    # ── Announce ──────────────────────────────────────────────────────────────

    def announce(self, event: str = "") -> list[dict]:
        """
        Send an announce request to the tracker.
        event: "started" | "completed" | "stopped" | ""
        Returns list of peers: [{"ip": ..., "port": ...}, ...]
        """
        params = {
            "info_hash":  self.info_hash,
            "peer_id":    self.peer_id,
            "port":       self.local_port,
            "uploaded":   self.uploaded,
            "downloaded": self.downloaded,
            "left":       self.left,
            "compact":    0,
        }
        if event:
            params["event"] = event

        # URL-encode manually to preserve raw bytes for info_hash and peer_id
        query = self._encode_params(params)
        url   = self.tracker_url + "?" + query

        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                raw = resp.read()
        except Exception as e:
            print(f"[TRACKER CLIENT] Announce failed: {e}")
            return []

        response, _ = bdecode(raw)

        if b"failure reason" in response:
            print(f"[TRACKER CLIENT] Tracker error: {response[b'failure reason'].decode()}")
            return []

        interval = response.get(b"interval", 30)
        raw_peers = response.get(b"peers", [])

        peers = []
        for p in raw_peers:
            peers.append({
                "ip":      p[b"ip"].decode(),
                "port":    p[b"port"],
                "peer_id": p[b"peer id"],
            })

        seeders  = response.get(b"complete",   0)
        leechers = response.get(b"incomplete", 0)

        print(f"[TRACKER CLIENT] Announced '{event or 're-announce'}' → "
              f"{len(peers)} peers, {seeders} seeders, {leechers} leechers")

        with self._lock:
            self._peers = peers

        return peers

    # ── Background re-announce loop ───────────────────────────────────────────

    def start(self):
        """Announce 'started' then keep re-announcing in background."""
        self.announce("started")
        t = threading.Thread(target=self._reannounce_loop, daemon=True)
        t.start()

    def stop(self):
        """Announce 'stopped' and halt re-announce loop."""
        self._stop.set()
        self.announce("stopped")

    def completed(self):
        """Announce 'completed' when download finishes."""
        self.left = 0
        self.announce("completed")

    def _reannounce_loop(self):
        interval = 30
        while not self._stop.wait(interval):
            self.announce()

    # ── Peer list ─────────────────────────────────────────────────────────────

    def get_peers(self) -> list[dict]:
        with self._lock:
            return list(self._peers)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _encode_params(self, params: dict) -> str:
        """URL-encode params, keeping binary values (info_hash, peer_id) as raw bytes."""
        parts = []
        for k, v in params.items():
            key = urllib.parse.quote(str(k), safe="")
            if isinstance(v, bytes):
                val = urllib.parse.quote(v, safe="")
            else:
                val = urllib.parse.quote(str(v), safe="")
            parts.append(f"{key}={val}")
        return "&".join(parts)


# ─────────────────────────────────────────────
# QUICK TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python tracker_client.py <file.torrent> [port]")
        sys.exit(1)

    torrent_path = sys.argv[1]
    port         = int(sys.argv[2]) if len(sys.argv) > 2 else 9001

    client = TrackerClient(torrent_path, local_port=port)
    peers  = client.announce("started")

    if peers:
        print(f"\n[TEST] Found {len(peers)} peer(s):")
        for p in peers:
            print(f"  → {p['ip']}:{p['port']}")
    else:
        print("\n[TEST] No peers found (are you the first?)")

    client.announce("stopped")