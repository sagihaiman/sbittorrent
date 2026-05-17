import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote_to_bytes
from torrent_files.torrent import bencode

# ─────────────────────────────────────────────
# TRACKER STATE
# ─────────────────────────────────────────────

ANNOUNCE_INTERVAL = 30        # seconds between client re-announces
PEER_TIMEOUT      = 90        # drop peers who haven't announced in this long

# peers[info_hash][peer_id] = {ip, port, uploaded, downloaded, left, last_seen}
peers = {}
peers_lock = threading.Lock()


def cleanup_peers():
    """Remove peers that haven't announced recently."""
    while True:
        time.sleep(30)
        now = time.time()
        with peers_lock:
            for info_hash in list(peers.keys()):
                for peer_id in list(peers[info_hash].keys()):
                    if now - peers[info_hash][peer_id]["last_seen"] > PEER_TIMEOUT:
                        print(f"[TRACKER] Dropping stale peer {peer_id.hex()[:8]} for {info_hash.hex()[:8]}")
                        del peers[info_hash][peer_id]
                if not peers[info_hash]:
                    del peers[info_hash]


# ─────────────────────────────────────────────
# REQUEST HANDLER
# ─────────────────────────────────────────────

class TrackerHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # silence default HTTP logging; we do our own

    def send_bencode(self, data: dict):
        encoded = bencode(data)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_error_bencode(self, reason: str):
        self.send_bencode({"failure reason": reason})

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/announce":
            self.handle_announce(parsed.query)
        elif parsed.path == "/scrape":
            self.handle_scrape(parsed.query)
        else:
            self.send_response(404)
            self.end_headers()

    # ── Announce ──────────────────────────────────────────────────────────────

    def handle_announce(self, query: str):
        params = parse_qs(query, keep_blank_values=True)

        # ── Parse required fields ─────────────────────────────────────────────
        try:
            # info_hash and peer_id are raw URL-encoded bytes
            raw_query = query.encode("latin-1")
            info_hash = self._extract_raw_param(raw_query, b"info_hash")
            peer_id   = self._extract_raw_param(raw_query, b"peer_id")

            port       = int(params["port"][0])
            uploaded   = int(params.get("uploaded",   ["0"])[0])
            downloaded = int(params.get("downloaded", ["0"])[0])
            left       = int(params.get("left",       ["0"])[0])
            event      = params.get("event", [""])[0]
        except (KeyError, ValueError) as e:
            self.send_error_bencode(f"Missing or invalid parameter: {e}")
            return

        if len(info_hash) != 20 or len(peer_id) != 20:
            self.send_error_bencode("info_hash and peer_id must be 20 bytes")
            return

        # ── Client IP ─────────────────────────────────────────────────────────
        ip = self.client_address[0]

        print(f"[TRACKER] Announce from {ip}:{port} | event={event or 'none'} "
              f"| torrent={info_hash.hex()[:8]}... | peer={peer_id.hex()[:8]}...")

        # ── Update peer table ─────────────────────────────────────────────────
        with peers_lock:
            if info_hash not in peers:
                peers[info_hash] = {}

            if event == "stopped":
                peers[info_hash].pop(peer_id, None)
                print(f"[TRACKER] Peer {peer_id.hex()[:8]} left")
            else:
                peers[info_hash][peer_id] = {
                    "ip":         ip,
                    "port":       port,
                    "uploaded":   uploaded,
                    "downloaded": downloaded,
                    "left":       left,
                    "last_seen":  time.time(),
                }

            # Build peer list (exclude the requesting peer)
            peer_list = [
                {
                    "peer id": pid,
                    "ip":      p["ip"],
                    "port":    p["port"],
                }
                for pid, p in peers[info_hash].items()
                if pid != peer_id
            ]

            seeders  = sum(1 for p in peers[info_hash].values() if p["left"] == 0)
            leechers = len(peers[info_hash]) - seeders

        print(f"[TRACKER] Torrent {info_hash.hex()[:8]}: "
              f"{seeders} seeders, {leechers} leechers, {len(peer_list)} peers returned")

        self.send_bencode({
            "interval": ANNOUNCE_INTERVAL,
            "complete":   seeders,
            "incomplete": leechers,
            "peers":      peer_list,
        })

    # ── Scrape ────────────────────────────────────────────────────────────────

    def handle_scrape(self, query: str):
        """Returns stats for all tracked torrents (or specific ones if requested)."""
        with peers_lock:
            files = {}
            for info_hash, peer_dict in peers.items():
                seeders  = sum(1 for p in peer_dict.values() if p["left"] == 0)
                leechers = len(peer_dict) - seeders
                files[info_hash] = {
                    "complete":   seeders,
                    "incomplete": leechers,
                    "downloaded": 0,  # we don't track this yet
                }
        self.send_bencode({"files": files})

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _extract_raw_param(self, raw_query: bytes, key: bytes) -> bytes:
        """
        Extract a URL-encoded binary parameter (like info_hash) from the raw
        query string. urllib.parse.parse_qs mangles raw bytes so we do it manually.
        """
        prefix = key + b"="
        for part in raw_query.split(b"&"):
            if part.startswith(prefix):
                return unquote_to_bytes(part[len(prefix):])
        raise KeyError(key.decode())


# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────

def run_tracker(host: str = "0.0.0.0", port: int = 8000):
    # Start cleanup thread
    t = threading.Thread(target=cleanup_peers, daemon=True)
    t.start()

    server = HTTPServer((host, port), TrackerHandler)
    print(f"[TRACKER] Running on http://{host}:{port}")
    print(f"[TRACKER] Announce URL: http://{host}:{port}/announce")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[TRACKER] Shutting down")
        server.server_close()


if __name__ == "__main__":
    run_tracker()