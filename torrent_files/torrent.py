import hashlib
import math
import os
import time

# ─────────────────────────────────────────────
# BENCODE
# ─────────────────────────────────────────────

def bencode(value) -> bytes:
    """Encode a value into bencode format."""
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
        # Keys must be sorted in bencode
        result = b"d"
        for k in sorted(value.keys()):
            result += bencode(k) + bencode(value[k])
        result += b"e"
        return result

    else:
        raise TypeError(f"Cannot bencode type: {type(value)}")


def bdecode(data: bytes, idx: int = 0):
    """Decode bencoded bytes. Returns (value, next_index)."""

    if data[idx:idx+1] == b"i":
        # Integer: i<number>e
        end = data.index(b"e", idx)
        return int(data[idx+1:end]), end + 1

    elif data[idx:idx+1] == b"l":
        # List: l<items>e
        idx += 1
        result = []
        while data[idx:idx+1] != b"e":
            item, idx = bdecode(data, idx)
            result.append(item)
        return result, idx + 1

    elif data[idx:idx+1] == b"d":
        # Dict: d<key><value>...e
        idx += 1
        result = {}
        while data[idx:idx+1] != b"e":
            key, idx = bdecode(data, idx)
            val, idx = bdecode(data, idx)
            result[key] = val
        return result, idx + 1

    elif data[idx:idx+1].isdigit():
        # String: <length>:<data>
        colon = data.index(b":", idx)
        length = int(data[idx:colon])
        start = colon + 1
        return data[start:start+length], start + length

    else:
        raise ValueError(f"Unexpected character at index {idx}: {data[idx:idx+1]}")


# ─────────────────────────────────────────────
# .TORRENT FILE BUILDER
# ─────────────────────────────────────────────

PIECE_LENGTH = 256 * 1024  # 256KB pieces (standard for small/medium files)

def hash_pieces(file_path: str, piece_length: int) -> bytes:
    """Read file and return concatenated SHA1 hashes of each piece."""
    pieces = b""
    with open(file_path, "rb") as f:
        while True:
            piece = f.read(piece_length)
            if not piece:
                break
            pieces += hashlib.sha1(piece).digest()
    return pieces

def create_torrent(file_path: str, tracker_url: str, out_path: str = None) -> dict:
    """
    Create a .torrent file for the given file.
    Returns the torrent dict and writes it to out_path.
    """
    file_name = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    pieces    = hash_pieces(file_path, PIECE_LENGTH)
    num_pieces = math.ceil(file_size / PIECE_LENGTH)

    info = {
        "name":         file_name,
        "length":       file_size,
        "piece length": PIECE_LENGTH,
        "pieces":       pieces,       # raw bytes: 20 bytes per piece
    }

    torrent = {
        "announce":      tracker_url,
        "info":          info,
        "created by":    "our-torrent-client/0.1",
        "creation date": int(time.time()),
        "encoding":      "UTF-8",
    }

    # Write .torrent file
    if out_path is None:
        out_path = file_name + ".torrent"

    with open(out_path, "wb") as f:
        f.write(bencode(torrent))

    # Compute info_hash (SHA1 of bencoded info dict)
    info_hash = hashlib.sha1(bencode(info)).digest()

    print(f"[TORRENT] Created: {out_path}")
    print(f"[TORRENT] File:    {file_name} ({file_size} bytes)")
    print(f"[TORRENT] Pieces:  {num_pieces} x {PIECE_LENGTH // 1024}KB")
    print(f"[TORRENT] Hash:    {info_hash.hex()}")

    return torrent, info_hash, out_path


def load_torrent(torrent_path: str) -> tuple[dict, bytes]:
    """
    Load a .torrent file.
    Returns (torrent_dict, info_hash).
    """
    with open(torrent_path, "rb") as f:
        data = f.read()

    torrent, _ = bdecode(data)

    # Recompute info_hash from the raw bencoded info section
    # We need to find the raw bytes of the info value, not re-encode it
    info_start = data.index(b"4:info") + len(b"4:info")
    # Find end of info dict by re-encoding and comparing lengths
    info_dict, info_end = bdecode(data, info_start)
    info_hash = hashlib.sha1(data[info_start:info_end]).digest()

    print(f"[TORRENT] Loaded:  {torrent_path}")
    print(f"[TORRENT] File:    {torrent[b'info'][b'name'].decode()}")
    print(f"[TORRENT] Tracker: {torrent[b'announce'].decode()}")
    print(f"[TORRENT] Hash:    {info_hash.hex()}")

    return torrent, info_hash


# ─────────────────────────────────────────────
# QUICK TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python torrent.py <file> [tracker_url]")
        sys.exit(1)

    file_path   = sys.argv[1]
    tracker_url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000/announce"

    # Create
    torrent, info_hash, torrent_path = create_torrent(file_path, tracker_url)

    # Round-trip: load it back and verify
    print()
    loaded, loaded_hash = load_torrent(torrent_path)
    assert info_hash == loaded_hash, "Hash mismatch after round-trip!"
    print(f"[TORRENT] Round-trip check: ✅ OK")