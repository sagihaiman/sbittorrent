import hashlib
import math
import os
import time

# ─────────────────────────────────────────────
# BENCODE
# ─────────────────────────────────────────────

def bencode(value) -> bytes:
    if isinstance(value, int):
        return b"i" + str(value).encode() + b"e"
    elif isinstance(value, bytes):
        return str(len(value)).encode() + b":" + value
    elif isinstance(value, str):
        encoded = value.encode("utf-8")
        return str(len(encoded)).encode() + b":" + encoded
    elif isinstance(value, list):
        return b"l" + b"".join(bencode(v) for v in value) + b"e"
    elif isinstance(value, dict):
        result = b"d"
        for k in sorted(value.keys()):
            result += bencode(k) + bencode(value[k])
        result += b"e"
        return result
    else:
        raise TypeError(f"Cannot bencode type: {type(value)}")


def bdecode(data: bytes, idx: int = 0):
    if data[idx:idx+1] == b"i":
        end = data.index(b"e", idx)
        return int(data[idx+1:end]), end + 1
    elif data[idx:idx+1] == b"l":
        idx += 1
        result = []
        while data[idx:idx+1] != b"e":
            item, idx = bdecode(data, idx)
            result.append(item)
        return result, idx + 1
    elif data[idx:idx+1] == b"d":
        idx += 1
        result = {}
        while data[idx:idx+1] != b"e":
            key, idx = bdecode(data, idx)
            val, idx = bdecode(data, idx)
            result[key] = val
        return result, idx + 1
    elif data[idx:idx+1].isdigit():
        colon = data.index(b":", idx)
        length = int(data[idx:colon])
        start = colon + 1
        return data[start:start+length], start + length
    else:
        raise ValueError(f"Unexpected character at index {idx}: {data[idx:idx+1]}")


# ─────────────────────────────────────────────
# TRACKER LIST HELPERS
# ─────────────────────────────────────────────

def get_tracker_list(torrent: dict) -> list:
    """Extract all tracker URLs from a torrent dict, in tier order."""
    trackers = []
    seen = set()

    if b"announce-list" in torrent:
        for tier in torrent[b"announce-list"]:
            for url in tier:
                decoded = url.decode() if isinstance(url, bytes) else url
                if decoded not in seen:
                    trackers.append(decoded)
                    seen.add(decoded)

    if b"announce" in torrent:
        primary = torrent[b"announce"]
        decoded = primary.decode() if isinstance(primary, bytes) else primary
        if decoded not in seen:
            trackers.append(decoded)

    return trackers


# ─────────────────────────────────────────────
# .TORRENT FILE BUILDER
# ─────────────────────────────────────────────

PIECE_LENGTH = 256 * 1024  # 256KB

def hash_pieces(file_path: str, piece_length: int) -> bytes:
    pieces = b""
    with open(file_path, "rb") as f:
        while True:
            piece = f.read(piece_length)
            if not piece:
                break
            pieces += hashlib.sha1(piece).digest()
    return pieces


def create_torrent(file_path: str, tracker_urls, out_path: str = None):
    """
    Create a .torrent file for the given file.
    tracker_urls: a single URL string or a list of URLs.
    Returns (torrent_dict, info_hash, out_path).
    """
    if isinstance(tracker_urls, str):
        tracker_urls = [tracker_urls]

    file_name  = os.path.basename(file_path)
    file_size  = os.path.getsize(file_path)
    pieces     = hash_pieces(file_path, PIECE_LENGTH)
    num_pieces = math.ceil(file_size / PIECE_LENGTH)

    info = {
        "name":         file_name,
        "length":       file_size,
        "piece length": PIECE_LENGTH,
        "pieces":       pieces,
    }

    torrent = {
        "announce":      tracker_urls[0],
        "announce-list": [[url] for url in tracker_urls],
        "info":          info,
        "created by":    "our-torrent-client/0.1",
        "creation date": int(time.time()),
        "encoding":      "UTF-8",
    }

    if out_path is None:
        out_path = file_name + ".torrent"

    with open(out_path, "wb") as f:
        f.write(bencode(torrent))

    info_hash = hashlib.sha1(bencode(info)).digest()

    print(f"[TORRENT] Created:  {out_path}")
    print(f"[TORRENT] File:     {file_name} ({file_size} bytes)")
    print(f"[TORRENT] Pieces:   {num_pieces} x {PIECE_LENGTH // 1024}KB")
    print(f"[TORRENT] Trackers: {', '.join(tracker_urls)}")
    print(f"[TORRENT] Hash:     {info_hash.hex()}")

    return torrent, info_hash, out_path


def load_torrent(torrent_path: str):
    """Load a .torrent file. Returns (torrent_dict, info_hash)."""
    with open(torrent_path, "rb") as f:
        data = f.read()

    torrent, _ = bdecode(data)

    info_start = data.index(b"4:info") + len(b"4:info")
    info_dict, info_end = bdecode(data, info_start)
    info_hash = hashlib.sha1(data[info_start:info_end]).digest()

    trackers = get_tracker_list(torrent)

    print(f"[TORRENT] Loaded:   {torrent_path}")
    print(f"[TORRENT] File:     {torrent[b'info'][b'name'].decode()}")
    print(f"[TORRENT] Trackers: {', '.join(trackers)}")
    print(f"[TORRENT] Hash:     {info_hash.hex()}")

    return torrent, info_hash


# ─────────────────────────────────────────────
# QUICK TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python torrent.py <file> [tracker_url ...]")
        sys.exit(1)

    file_path    = sys.argv[1]
    tracker_urls = sys.argv[2:] if len(sys.argv) > 2 else ["http://localhost:8000/announce"]

    torrent, info_hash, torrent_path = create_torrent(file_path, tracker_urls)

    print()
    loaded, loaded_hash = load_torrent(torrent_path)
    assert info_hash == loaded_hash, "Hash mismatch after round-trip!"
    print(f"[TORRENT] Round-trip check: OK")