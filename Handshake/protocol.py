import struct
import socket
import hashlib
import os

# ─────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────

HEADER_FORMAT = "!HHHHBH"  # src_port, dst_port, length, checksum, type, conn_id
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

MSG_ENSURE_CONNECTION  = 0
MSG_CONFIRM_CONNECTION = 1
MSG_REQUEST_INDEX      = 2
MSG_SEND_INDEX         = 3
MSG_SEND_HASH          = 4
MSG_CONFIRM_FINISH     = 5
MSG_ACK                = 6

CHUNK_SIZE = 8 * 1024  # 8KB — safe UDP payload size

# ─────────────────────────────────────────────
# CHECKSUM
# ─────────────────────────────────────────────

def checksum(data: bytes) -> int:
    s = 0
    for i in range(0, len(data) - 1, 2):
        s += (data[i] << 8) + data[i + 1]
    if len(data) % 2:
        s += data[-1] << 8
    while s >> 16:
        s = (s >> 16) + (s & 0xFFFF)
    return ~s & 0xFFFF

# ─────────────────────────────────────────────
# PACKET BUILD / PARSE
# ─────────────────────────────────────────────

def build_packet(src_port: int, dst_port: int, msg_type: int, conn_id: int, payload: bytes = b"") -> bytes:
    length = HEADER_SIZE + len(payload)
    header = struct.pack(HEADER_FORMAT, src_port, dst_port, length, 0, msg_type, conn_id)
    raw = header + payload
    chk = checksum(raw)
    header = struct.pack(HEADER_FORMAT, src_port, dst_port, length, chk, msg_type, conn_id)
    return header + payload

def parse_packet(data: bytes) -> dict:
    if len(data) < HEADER_SIZE:
        raise ValueError("Packet too short")
    src_port, dst_port, length, chk, msg_type, conn_id = struct.unpack(
        HEADER_FORMAT, data[:HEADER_SIZE]
    )
    payload = data[HEADER_SIZE:]
    raw = data[:6] + b'\x00\x00' + data[8:]
    if checksum(raw) != chk:
        raise ValueError("Checksum mismatch")
    return {
        "src_port": src_port,
        "dst_port": dst_port,
        "length":   length,
        "checksum": chk,
        "type":     msg_type,
        "conn_id":  conn_id,
        "payload":  payload,
    }

# ─────────────────────────────────────────────
# PAYLOAD BUILDERS
# ─────────────────────────────────────────────

def build_type0_payload(file_hash: bytes) -> bytes:
    """Ensure connection — leech sends file hash (20 bytes SHA1)."""
    assert len(file_hash) == 20, "Hash must be 20 bytes (SHA1)"
    return file_hash

def build_type1_payload(num_indexes: int, conn_id: int) -> bytes:
    """Confirm connection — seed sends confirmation string + num indexes + conn_id."""
    msg = b"connection established."
    return msg + struct.pack("!HH", num_indexes, conn_id)

def build_type2_payload(index: int) -> bytes:
    """Request data at index — leech sends the index it wants."""
    return struct.pack("!H", index)

def build_type3_payload(index: int, data: bytes) -> bytes:
    """Send data at index — seed sends index + chunk data."""
    return struct.pack("!H", index) + data

def build_type4_payload(file_hash: bytes) -> bytes:
    """Send assembled file hash — leech sends hash for verification."""
    assert len(file_hash) == 20
    return file_hash

def build_type5_payload(success: bool) -> bytes:
    """Confirm and finish — seed sends 1 (success) or 0 (failure)."""
    return struct.pack("!B", 1 if success else 0)

def build_ack_payload(index: int) -> bytes:
    """ACK — leech confirms receipt of a chunk at index."""
    return struct.pack("!H", index)

# ─────────────────────────────────────────────
# PAYLOAD PARSERS
# ─────────────────────────────────────────────

def parse_type0(payload: bytes) -> dict:
    return {"file_hash": payload[:20]}

def parse_type1(payload: bytes) -> dict:
    msg_len = len(b"connection established.")
    msg = payload[:msg_len]
    num_indexes, conn_id = struct.unpack("!HH", payload[msg_len:msg_len + 4])
    return {"message": msg.decode(), "num_indexes": num_indexes, "conn_id": conn_id}

def parse_type2(payload: bytes) -> dict:
    index, = struct.unpack("!H", payload[:2])
    return {"index": index}

def parse_type3(payload: bytes) -> dict:
    index, = struct.unpack("!H", payload[:2])
    return {"index": index, "data": payload[2:]}

def parse_type4(payload: bytes) -> dict:
    return {"file_hash": payload[:20]}

def parse_type5(payload: bytes) -> dict:
    success, = struct.unpack("!B", payload[:1])
    return {"success": bool(success)}

def parse_ack(payload: bytes) -> dict:
    index, = struct.unpack("!H", payload[:2])
    return {"index": index}

PAYLOAD_PARSERS = {
    MSG_ENSURE_CONNECTION:  parse_type0,
    MSG_CONFIRM_CONNECTION: parse_type1,
    MSG_REQUEST_INDEX:      parse_type2,
    MSG_SEND_INDEX:         parse_type3,
    MSG_SEND_HASH:          parse_type4,
    MSG_CONFIRM_FINISH:     parse_type5,
    MSG_ACK:                parse_ack,
}

def parse_payload(msg_type: int, payload: bytes) -> dict:
    parser = PAYLOAD_PARSERS.get(msg_type)
    if not parser:
        raise ValueError(f"Unknown message type: {msg_type}")
    return parser(payload)

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def file_sha1(path: str) -> bytes:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.digest()

def split_file(path: str) -> list[bytes]:
    chunks = []
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            chunks.append(chunk)
    return chunks

def reassemble_file(chunks: list[bytes], out_path: str):
    with open(out_path, "wb") as f:
        for chunk in chunks:
            f.write(chunk)

# ─────────────────────────────────────────────
# SEEDER
# ─────────────────────────────────────────────

def run_seeder(file_path: str, host: str = "0.0.0.0", port: int = 9000, file_hash: bytes = None):
    file_hash = file_hash or file_sha1(file_path)
    chunks = split_file(file_path)
    num_indexes = len(chunks)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    print(f"[SEEDER] Listening on {host}:{port}")
    print(f"[SEEDER] File: {file_path} | Chunks: {num_indexes} | Hash: {file_hash.hex()}")

    conn_id_counter = 1
    active_connections = {}  # conn_id -> leech_addr

    while True:
        data, addr = sock.recvfrom(65535)
        try:
            pkt = parse_packet(data)
        except ValueError as e:
            print(f"[SEEDER] Bad packet from {addr}: {e}")
            continue

        msg_type = pkt["type"]
        payload = parse_payload(msg_type, pkt["payload"])
        leech_port = pkt["src_port"]

        # Type 0: Ensure connection
        if msg_type == MSG_ENSURE_CONNECTION:
            if payload["file_hash"] != file_hash:
                print(f"[SEEDER] Hash mismatch from {addr}, ignoring.")
                continue
            conn_id = conn_id_counter % 0xFFFF
            conn_id_counter += 1
            active_connections[conn_id] = addr
            print(f"[SEEDER] New connection from {addr} | conn_id={conn_id}")

            p = build_type1_payload(num_indexes, conn_id)
            pkt_out = build_packet(port, leech_port, MSG_CONFIRM_CONNECTION, conn_id, p)
            sock.sendto(pkt_out, addr)

        # Type 2: Request data at index
        elif msg_type == MSG_REQUEST_INDEX:
            conn_id = pkt["conn_id"]
            if conn_id not in active_connections:
                print(f"[SEEDER] Unknown conn_id {conn_id} from {addr}")
                continue
            index = payload["index"]
            if index >= num_indexes:
                print(f"[SEEDER] Invalid index {index} requested")
                continue
            print(f"[SEEDER] Sending chunk {index}/{num_indexes - 1} to {addr}")
            p = build_type3_payload(index, chunks[index])
            pkt_out = build_packet(port, leech_port, MSG_SEND_INDEX, conn_id, p)
            sock.sendto(pkt_out, addr)

        # Type 4: Leech sends assembled file hash
        elif msg_type == MSG_SEND_HASH:
            conn_id = pkt["conn_id"]
            success = payload["file_hash"] == file_hash
            print(f"[SEEDER] Hash check for conn_id={conn_id}: {'OK' if success else 'FAIL'}")
            p = build_type5_payload(success)
            pkt_out = build_packet(port, leech_port, MSG_CONFIRM_FINISH, conn_id, p)
            sock.sendto(pkt_out, addr)
            if conn_id in active_connections:
                del active_connections[conn_id]

        # Type 6: ACK
        elif msg_type == MSG_ACK:
            print(f"[SEEDER] ACK for chunk {payload['index']} from {addr}")

        else:
            print(f"[SEEDER] Unexpected message type {msg_type} from {addr}")

# ─────────────────────────────────────────────
# LEECHER
# ─────────────────────────────────────────────

def run_leecher(file_hash: bytes, num_expected_chunks: int, out_path: str,
                seeder_host: str = "127.0.0.1", seeder_port: int = 9000,
                local_port: int = 9001):

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", local_port))
    sock.settimeout(5.0)

    seeder_addr = (seeder_host, seeder_port)
    conn_id = 0
    chunks = {}

    print(f"[LEECH] Connecting to seeder at {seeder_addr}")

    # Type 0: Ensure connection
    p = build_type0_payload(file_hash)
    sock.sendto(build_packet(local_port, seeder_port, MSG_ENSURE_CONNECTION, 0, p), seeder_addr)

    # Type 1: Confirm connection
    data, _ = sock.recvfrom(65535)
    pkt = parse_packet(data)
    assert pkt["type"] == MSG_CONFIRM_CONNECTION
    info = parse_payload(MSG_CONFIRM_CONNECTION, pkt["payload"])
    conn_id = info["conn_id"]
    num_indexes = info["num_indexes"]
    print(f"[LEECH] {info['message']} | conn_id={conn_id} | chunks={num_indexes}")

    # Type 2 & 3: Request and receive all chunks
    for index in range(num_indexes):
        while True:
            p = build_type2_payload(index)
            sock.sendto(build_packet(local_port, seeder_port, MSG_REQUEST_INDEX, conn_id, p), seeder_addr)
            try:
                data, _ = sock.recvfrom(65535)
                pkt = parse_packet(data)
                if pkt["type"] == MSG_SEND_INDEX:
                    chunk_info = parse_payload(MSG_SEND_INDEX, pkt["payload"])
                    chunks[chunk_info["index"]] = chunk_info["data"]
                    print(f"[LEECH] Received chunk {chunk_info['index']}/{num_indexes - 1}")

                    # Send ACK
                    ack = build_ack_payload(chunk_info["index"])
                    sock.sendto(build_packet(local_port, seeder_port, MSG_ACK, conn_id, ack), seeder_addr)
                    break
            except socket.timeout:
                print(f"[LEECH] Timeout on chunk {index}, retrying...")

    # Reassemble
    ordered_chunks = [chunks[i] for i in range(num_indexes)]
    reassemble_file(ordered_chunks, out_path)

    # Type 4: Send assembled file hash
    assembled_hash = file_sha1(out_path)
    p = build_type4_payload(assembled_hash)
    sock.sendto(build_packet(local_port, seeder_port, MSG_SEND_HASH, conn_id, p), seeder_addr)

    # Type 5: Confirm and finish
    data, _ = sock.recvfrom(65535)
    pkt = parse_packet(data)
    result = parse_payload(MSG_CONFIRM_FINISH, pkt["payload"])
    if result["success"]:
        print(f"[LEECH] Transfer complete! File saved to {out_path}")
    else:
        print(f"[LEECH] Hash mismatch! File may be corrupted.")

    sock.close()