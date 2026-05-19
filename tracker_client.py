import os
import threading
import urllib.request
import urllib.parse
from torrent import bdecode, load_torrent, get_tracker_list

# ─────────────────────────────────────────────
# PEER ID
# ─────────────────────────────────────────────

def make_peer_id() -> bytes:
    prefix = b"-OT0001-"
    return prefix + os.urandom(12)


# ─────────────────────────────────────────────
# TRACKER CLIENT (single torrent)
# ─────────────────────────────────────────────

class TrackerClient:
    def __init__(self, torrent_path: str, local_port: int, peer_id: bytes = None):
        self.torrent, self.info_hash = load_torrent(torrent_path)
        self.local_port   = local_port
        self.peer_id      = peer_id or make_peer_id()
        self.tracker_urls = get_tracker_list(self.torrent)
        self.downloaded   = 0
        self.uploaded     = 0
        self.left         = self.torrent[b"info"][b"length"]
        self._stop        = threading.Event()
        self._peers       = []
        self._lock        = threading.Lock()

        if not self.tracker_urls:
            raise ValueError("No tracker URLs found in torrent file")

    def _announce_one(self, tracker_url: str, event: str = "") -> list:
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

        url = tracker_url + "?" + self._encode_params(params)
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                raw = resp.read()
        except Exception as e:
            print(f"[TRACKER CLIENT] {tracker_url} failed: {e}")
            return []

        response, _ = bdecode(raw)
        if b"failure reason" in response:
            print(f"[TRACKER CLIENT] {tracker_url} error: {response[b'failure reason'].decode()}")
            return []

        raw_peers = response.get(b"peers", [])
        peers = [{"ip": p[b"ip"].decode(), "port": p[b"port"], "peer_id": p[b"peer id"]}
                 for p in raw_peers]

        seeders  = response.get(b"complete",   0)
        leechers = response.get(b"incomplete", 0)
        print(f"[TRACKER CLIENT] {tracker_url} → "
              f"{len(peers)} peers, {seeders} seeders, {leechers} leechers")
        return peers

    def announce(self, event: str = "") -> list:
        """Announce to all trackers in parallel, return deduplicated peer list."""
        results = [[] for _ in self.tracker_urls]
        threads = []

        def fetch(i, url):
            results[i] = self._announce_one(url, event)

        for i, url in enumerate(self.tracker_urls):
            t = threading.Thread(target=fetch, args=(i, url), daemon=True)
            t.start()
            threads.append(t)

        for t in threads:
            t.join(timeout=12)

        seen, peers = set(), []
        for peer_list in results:
            for p in peer_list:
                key = (p["ip"], p["port"])
                if key not in seen:
                    seen.add(key)
                    peers.append(p)

        print(f"[TRACKER CLIENT] '{event or 're-announce'}' → "
              f"{len(peers)} unique peers across {len(self.tracker_urls)} tracker(s)")

        with self._lock:
            self._peers = peers
        return peers

    def start(self):
        """Announce 'started' then re-announce in background."""
        self.announce("started")
        t = threading.Thread(target=self._reannounce_loop, daemon=True)
        t.start()

    def stop(self):
        self._stop.set()
        self.announce("stopped")

    def completed(self):
        self.left = 0
        self.announce("completed")

    def _reannounce_loop(self):
        while not self._stop.wait(30):
            self.announce()

    def get_peers(self) -> list:
        with self._lock:
            return list(self._peers)

    def _encode_params(self, params: dict) -> str:
        parts = []
        for k, v in params.items():
            key = urllib.parse.quote(str(k), safe="")
            val = urllib.parse.quote(v, safe="") if isinstance(v, bytes) else urllib.parse.quote(str(v), safe="")
            parts.append(f"{key}={val}")
        return "&".join(parts)


# ─────────────────────────────────────────────
# MULTI TRACKER CLIENT (multiple torrents)
# Manages one TrackerClient per torrent.
# ─────────────────────────────────────────────

class MultiTrackerClient:
    def __init__(self, local_port: int, peer_id: bytes = None):
        """
        local_port: the port this peer serves on (same for all torrents)
        peer_id:    shared peer identity across all torrents
        """
        self.local_port = local_port
        self.peer_id    = peer_id or make_peer_id()
        self._clients   = {}   # info_hash (hex) -> TrackerClient
        self._lock      = threading.Lock()

    def add_torrent(self, torrent_path: str, uploaded: int = 0, left: int = None) -> str:
        """
        Add a torrent to track. Returns the info_hash hex string.
        uploaded: bytes already uploaded (set to file size if seeding)
        left:     bytes remaining (set to 0 if seeding, file size if leeching)
        """
        client = TrackerClient(torrent_path, local_port=self.local_port, peer_id=self.peer_id)
        if uploaded is not None:
            client.uploaded = uploaded
        if left is not None:
            client.left = left

        key = client.info_hash.hex()
        with self._lock:
            self._clients[key] = client

        print(f"[MULTI TRACKER] Added torrent: {torrent_path} | info_hash={key[:16]}...")
        return key

    def start_all(self):
        """Announce 'started' for all torrents and begin re-announcing."""
        with self._lock:
            clients = list(self._clients.values())
        threads = []
        for c in clients:
            t = threading.Thread(target=c.start, daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        print(f"[MULTI TRACKER] Announced {len(clients)} torrent(s)")

    def stop_all(self):
        """Announce 'stopped' for all torrents."""
        with self._lock:
            clients = list(self._clients.values())
        for c in clients:
            c.stop()

    def get_peers(self, info_hash_hex: str) -> list:
        """Get peers for a specific torrent by info_hash hex."""
        with self._lock:
            client = self._clients.get(info_hash_hex)
        return client.get_peers() if client else []

    def get_all_peers(self) -> dict:
        """Returns {info_hash_hex: [peers]} for all torrents."""
        with self._lock:
            clients = dict(self._clients)
        return {key: c.get_peers() for key, c in clients.items()}

    def completed(self, info_hash_hex: str):
        """Mark a specific torrent as completed."""
        with self._lock:
            client = self._clients.get(info_hash_hex)
        if client:
            client.completed()

    def list_torrents(self):
        """Print all tracked torrents and their peer counts."""
        with self._lock:
            clients = dict(self._clients)
        print(f"\n[MULTI TRACKER] Tracking {len(clients)} torrent(s):")
        for key, c in clients.items():
            name  = c.torrent[b"info"][b"name"].decode()
            peers = len(c.get_peers())
            print(f"  {key[:16]}... | {name} | {peers} peer(s)")