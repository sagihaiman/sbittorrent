import struct
import socket
import hashlib
import os
import threading
import queue

from cryptography.hazmat.primitives.asymmetric.dh import DHParameterNumbers
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ─────────────────────────────────────────────
# HARDCODED DH PARAMETERS (2048-bit)
# ─────────────────────────────────────────────

DH_P = 21584683433874298207291809801536878805145968932146928883077943609691303717759112441085423718724810532437329705728798988187520605592802971119300056061829334926105472118742638012218864368851168023903199688060818002331466487658929076030609143651128022009914311334065313857812520980603271343763212668998913036585851116533493109467055779032384102276796600852971840160384516302108723984891202616067933655228674094303554973799155263703111950248963349037225000099575739835161576309560274252902345803408034372764925596202862842070364452103425362264896727165967812575203121959194299350469362137586615716308071334013522476771839
DH_G = 2
DH_PARAMS = DHParameterNumbers(DH_P, DH_G).parameters(default_backend())

# ─────────────────────────────────────────────
# CRYPTO HELPERS
# ─────────────────────────────────────────────

def generate_dh_keypair():
    return DH_PARAMS.generate_private_key()

def dh_public_bytes(private_key) -> bytes:
    return private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo
    )

def dh_public_from_bytes(data: bytes):
    return serialization.load_pem_public_key(data, backend=default_backend())

def derive_aes_key(private_key, peer_public_key) -> bytes:
    shared_secret = private_key.exchange(peer_public_key)
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"torrent-encryption",
        backend=default_backend()
    ).derive(shared_secret)

def encrypt(aes_key: bytes, plaintext: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(aes_key).encrypt(nonce, plaintext, None)

def decrypt(aes_key: bytes, data: bytes) -> bytes:
    return AESGCM(aes_key).decrypt(data[:12], data[12:], None)

# ─────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────

HEADER_FORMAT = "!HHHHBH"
HEADER_SIZE   = struct.calcsize(HEADER_FORMAT)

MSG_ENSURE_CONNECTION  = 0
MSG_CONFIRM_CONNECTION = 1
MSG_REQUEST_INDEX      = 2
MSG_SEND_INDEX         = 3
MSG_SEND_HASH          = 4
MSG_CONFIRM_FINISH     = 5
MSG_ACK                = 6

CHUNK_SIZE  = 8 * 1024
MAX_WORKERS = 4

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

def build_packet(src_port, dst_port, msg_type, conn_id, payload=b""):
    length = HEADER_SIZE + len(payload)
    header = struct.pack(HEADER_FORMAT, src_port, dst_port, length, 0, msg_type, conn_id)
    chk    = checksum(header + payload)
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
        "src_port": src_port, "dst_port": dst_port,
        "length":   length,   "checksum": chk,
        "type":     msg_type, "conn_id":  conn_id,
        "payload":  payload,
    }

# ─────────────────────────────────────────────
# PAYLOAD BUILDERS / PARSERS
# type 0 and type 1 are unencrypted (handshake)
# type 2+ are encrypted
# ─────────────────────────────────────────────

def build_type0_payload(file_hash: bytes, dh_public: bytes) -> bytes:
    return file_hash + struct.pack("!H", len(dh_public)) + dh_public

def parse_type0(payload: bytes) -> dict:
    file_hash = payload[:20]
    pub_len,  = struct.unpack("!H", payload[20:22])
    return {"file_hash": file_hash, "dh_public": payload[22:22+pub_len]}

def build_type1_payload(num_indexes: int, conn_id: int, dh_public: bytes) -> bytes:
    return (b"connection established."
            + struct.pack("!HH", num_indexes, conn_id)
            + struct.pack("!H", len(dh_public))
            + dh_public)

def parse_type1(payload: bytes) -> dict:
    msg_len = len(b"connection established.")
    num_indexes, conn_id = struct.unpack("!HH", payload[msg_len:msg_len+4])
    pub_len, = struct.unpack("!H", payload[msg_len+4:msg_len+6])
    dh_public = payload[msg_len+6:msg_len+6+pub_len]
    return {"num_indexes": num_indexes, "conn_id": conn_id, "dh_public": dh_public}

def build_type2_payload(index):          return struct.pack("!H", index)
def build_type3_payload(index, data):    return struct.pack("!H", index) + data
def build_type4_payload(file_hash):      return file_hash
def build_type5_payload(success):        return struct.pack("!B", 1 if success else 0)
def build_ack_payload(index):            return struct.pack("!H", index)

def parse_type2(p): index, = struct.unpack("!H", p[:2]); return {"index": index}
def parse_type3(p): index, = struct.unpack("!H", p[:2]); return {"index": index, "data": p[2:]}
def parse_type4(p): return {"file_hash": p[:20]}
def parse_type5(p): s, = struct.unpack("!B", p[:1]); return {"success": bool(s)}
def parse_ack(p):   index, = struct.unpack("!H", p[:2]); return {"index": index}

PAYLOAD_PARSERS = {
    MSG_REQUEST_INDEX:  parse_type2,
    MSG_SEND_INDEX:     parse_type3,
    MSG_SEND_HASH:      parse_type4,
    MSG_CONFIRM_FINISH: parse_type5,
    MSG_ACK:            parse_ack,
}

def parse_encrypted_payload(msg_type, payload, aes_key):
    return PAYLOAD_PARSERS[msg_type](decrypt(aes_key, payload))

def build_encrypted_packet(src_port, dst_port, msg_type, conn_id, payload, aes_key):
    return build_packet(src_port, dst_port, msg_type, conn_id, encrypt(aes_key, payload))

# ─────────────────────────────────────────────
# FILE HELPERS
# ─────────────────────────────────────────────

def file_sha1(path: str) -> bytes:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.digest()

def split_file(path: str) -> list:
    chunks = []
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            chunks.append(chunk)
    return chunks

def reassemble_file(chunks: dict, num_chunks: int, out_path: str):
    with open(out_path, "wb") as f:
        for i in range(num_chunks):
            f.write(chunks[i])

# ─────────────────────────────────────────────
# SEEDER LIBRARY
# Maps info_hash -> {file_path, chunks, file_hash}
# Built from a list of (torrent_path, file_path) pairs.
# ─────────────────────────────────────────────

def build_seeder_library(torrent_file_pairs: dict) -> dict:
    """
    torrent_file_pairs: list of (torrent_path, file_path)
    Returns: {info_hash (bytes): {"file_path": ..., "chunks": [...], "file_hash": ...}}
    """
    from backend.torrent import load_torrent  # import here to avoid circular deps

    library = {}
    for torrent_path, file_path in torrent_file_pairs.items():
        if not os.path.exists(file_path):
            print(f"[SEEDER] WARNING: file not found: {file_path}, skipping")
            continue
        if not os.path.exists(torrent_path):
            print(f"[SEEDER] WARNING: torrent not found: {torrent_path}, skipping")
            continue

        _, info_hash = load_torrent(torrent_path)
        chunks       = split_file(file_path)
        fhash        = file_sha1(file_path)
        library[info_hash] = {
            "file_path": file_path,
            "chunks":    chunks,
            "file_hash": fhash,
        }
        print(f"[SEEDER] Registered: {os.path.basename(file_path)} "
              f"({len(chunks)} chunks) | info_hash={info_hash.hex()[:16]}...")

    print(f"[SEEDER] Library ready: {len(library)} file(s)")
    return library

# ─────────────────────────────────────────────
# SEEDER
# ─────────────────────────────────────────────

def run_seeder(library: dict = None,
               file_path: str = None, host: str = "0.0.0.0", port: int = 9000,
               file_hash: bytes = None):
    """
    Run the seeder.
    Pass either:
      - library: dict from build_seeder_library()  (multi-file mode)
      - file_path + optional file_hash             (single-file backwards compat)
    """
    # Build library from single file if needed
    if library is None:
        if file_path is None:
            raise ValueError("Provide library or file_path")
        fhash   = file_hash or file_sha1(file_path)
        chunks  = split_file(file_path)
        library = {fhash: {"file_path": file_path, "chunks": chunks, "file_hash": fhash}}

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    print(f"[SEEDER] Listening on {host}:{port} | serving {len(library)} file(s)")

    connections = {}  # conn_id -> queue
    conn_lock   = threading.Lock()

    def handle_connection(conn_id, addr, leech_port, pkt_queue, aes_key, entry):
        chunks    = entry["chunks"]
        file_hash = entry["file_hash"]
        num_indexes = len(chunks)
        print(f"[SEEDER] conn_id={conn_id} serving '{os.path.basename(entry['file_path'])}' to {addr}")

        while True:
            try:
                pkt, laddr = pkt_queue.get(timeout=30)
            except queue.Empty:
                print(f"[SEEDER] conn_id={conn_id} timed out")
                break

            msg_type = pkt["type"]
            lport    = pkt["src_port"]

            try:
                payload = parse_encrypted_payload(msg_type, pkt["payload"], aes_key)
            except Exception as e:
                print(f"[SEEDER] Decrypt error conn_id={conn_id}: {e}")
                continue

            if msg_type == MSG_REQUEST_INDEX:
                index = payload["index"]
                if index < num_indexes:
                    p = build_type3_payload(index, chunks[index])
                    sock.sendto(
                        build_encrypted_packet(port, lport, MSG_SEND_INDEX, conn_id, p, aes_key),
                        laddr
                    )

            elif msg_type == MSG_SEND_HASH:
                success = payload["file_hash"] == file_hash
                print(f"[SEEDER] conn_id={conn_id} hash check: {'OK' if success else 'FAIL'}")
                p = build_type5_payload(success)
                sock.sendto(
                    build_encrypted_packet(port, lport, MSG_CONFIRM_FINISH, conn_id, p, aes_key),
                    laddr
                )
                break

            elif msg_type == MSG_ACK:
                pass

        with conn_lock:
            connections.pop(conn_id, None)
        print(f"[SEEDER] conn_id={conn_id} closed")

    conn_id_counter = 1
    while True:
        data, addr = sock.recvfrom(65535)
        try:
            pkt = parse_packet(data)
        except ValueError as e:
            print(f"[SEEDER] Bad packet from {addr}: {e}")
            continue

        msg_type   = pkt["type"]
        conn_id    = pkt["conn_id"]
        leech_port = pkt["src_port"]

        if msg_type == MSG_ENSURE_CONNECTION:
            info      = parse_type0(pkt["payload"])
            info_hash = info["file_hash"]

            # Look up the requested file in the library
            entry = library.get(info_hash)
            if entry is None:
                print(f"[SEEDER] Requested info_hash not in library: {info_hash.hex()[:16]}... — rejecting")
                continue

            # DH exchange
            seeder_private = generate_dh_keypair()
            seeder_public  = dh_public_bytes(seeder_private)
            leecher_public = dh_public_from_bytes(info["dh_public"])
            aes_key        = derive_aes_key(seeder_private, leecher_public)

            new_conn_id = conn_id_counter % 0xFFFF or 1
            conn_id_counter += 1

            num_indexes = len(entry["chunks"])
            p = build_type1_payload(num_indexes, new_conn_id, seeder_public)
            sock.sendto(build_packet(port, leech_port, MSG_CONFIRM_CONNECTION, new_conn_id, p), addr)

            q = queue.Queue()
            with conn_lock:
                connections[new_conn_id] = q
            t = threading.Thread(
                target=handle_connection,
                args=(new_conn_id, addr, leech_port, q, aes_key, entry),
                daemon=True
            )
            t.start()

        else:
            with conn_lock:
                q = connections.get(conn_id)
            if q:
                q.put((pkt, addr))
            else:
                print(f"[SEEDER] Unknown conn_id={conn_id} from {addr}")

# ─────────────────────────────────────────────
# LEECHER
# ─────────────────────────────────────────────

def _download_from_peer(peer, file_hash, chunk_queue, results, results_lock, local_port, failed_chunks):
    seeder_host = peer["ip"]
    seeder_port = peer["port"]
    seeder_addr = (seeder_host, seeder_port)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", local_port))
    sock.settimeout(5.0)

    try:
        leecher_private = generate_dh_keypair()
        leecher_public  = dh_public_bytes(leecher_private)

        p = build_type0_payload(file_hash, leecher_public)
        sock.sendto(build_packet(local_port, seeder_port, MSG_ENSURE_CONNECTION, 0, p), seeder_addr)

        data, _ = sock.recvfrom(65535)
        pkt = parse_packet(data)
        if pkt["type"] != MSG_CONFIRM_CONNECTION:
            failed_chunks.append(("handshake", seeder_host, seeder_port))
            return

        info           = parse_type1(pkt["payload"])
        conn_id        = info["conn_id"]
        num_indexes    = info["num_indexes"]
        aes_key        = derive_aes_key(leecher_private, dh_public_from_bytes(info["dh_public"]))

        print(f"[LEECH] Connected to {seeder_host}:{seeder_port} | "
              f"conn_id={conn_id} | chunks={num_indexes} | encrypted")

        while True:
            try:
                index = chunk_queue.get_nowait()
            except queue.Empty:
                break

            downloaded = False
            for attempt in range(5):
                p = build_type2_payload(index)
                sock.sendto(
                    build_encrypted_packet(local_port, seeder_port, MSG_REQUEST_INDEX, conn_id, p, aes_key),
                    seeder_addr
                )
                try:
                    data, _ = sock.recvfrom(65535)
                    pkt = parse_packet(data)
                    if pkt["type"] == MSG_SEND_INDEX:
                        chunk_info = parse_encrypted_payload(MSG_SEND_INDEX, pkt["payload"], aes_key)
                        with results_lock:
                            results[chunk_info["index"]] = chunk_info["data"]
                        ack = build_ack_payload(chunk_info["index"])
                        sock.sendto(
                            build_encrypted_packet(local_port, seeder_port, MSG_ACK, conn_id, ack, aes_key),
                            seeder_addr
                        )
                        print(f"[LEECH] chunk {chunk_info['index']}/{num_indexes-1} ← {seeder_host}:{seeder_port}")
                        downloaded = True
                        break
                except socket.timeout:
                    print(f"[LEECH] Timeout chunk {index}, retry {attempt+1}/5")

            if not downloaded:
                chunk_queue.put(index)
                failed_chunks.append(index)
                break

            chunk_queue.task_done()

    except Exception as e:
        print(f"[LEECH] Worker error: {e}")
    finally:
        sock.close()


def run_leecher(file_hash: bytes, num_expected_chunks: int, out_path: str,
                peers: list = None,
                seeder_host: str = None, seeder_port: int = None,
                local_port: int = 9001):
    if peers is None:
        if seeder_host and seeder_port:
            peers = [{"ip": seeder_host, "port": seeder_port}]
        else:
            raise ValueError("Provide peers list or seeder_host+seeder_port")

    num_workers = min(MAX_WORKERS, len(peers))
    print(f"[LEECH] Downloading {num_expected_chunks} chunks from "
          f"{len(peers)} peer(s) using {num_workers} worker(s)")

    chunk_queue   = queue.Queue()
    for i in range(num_expected_chunks):
        chunk_queue.put(i)

    results       = {}
    results_lock  = threading.Lock()
    failed_chunks = []

    threads = []
    for i in range(num_workers):
        peer        = peers[i % len(peers)]
        worker_port = local_port + i
        t = threading.Thread(
            target=_download_from_peer,
            args=(peer, file_hash, chunk_queue, results, results_lock, worker_port, failed_chunks),
            daemon=True
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    if len(results) < num_expected_chunks:
        missing = [i for i in range(num_expected_chunks) if i not in results]
        raise RuntimeError(f"Download incomplete — missing chunks: {missing}")

    reassemble_file(results, num_expected_chunks, out_path)
    saved = False
    try:
        with open("kept_files.txt", "r") as f:
            lines = f.readlines()
            for row in lines:
                if row.find(out_path) != -1:
                    saved = True
                    break
        if saved:
            with open("kept_files.txt", "a") as f:
                f.write(out_path)
    except FileNotFoundError:
        open("kept_files.txt", "x").close()
        with open("kept_files.txt", "r") as f:
            lines = f.readlines()
            for row in lines:
                if row.find(out_path) != -1:
                    saved = True
                    break
        if saved:
            with open("kept_files.txt", "a") as f:
                f.write(out_path)




    # Hash verification
    assembled_hash = file_sha1(out_path)
    first_peer     = peers[0]
    verify_port    = local_port + num_workers

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5.0)
    sock.bind(("0.0.0.0", verify_port))

    try:
        leecher_private = generate_dh_keypair()
        leecher_public  = dh_public_bytes(leecher_private)

        p = build_type0_payload(file_hash, leecher_public)
        sock.sendto(
            build_packet(verify_port, first_peer["port"], MSG_ENSURE_CONNECTION, 0, p),
            (first_peer["ip"], first_peer["port"])
        )
        data, _  = sock.recvfrom(65535)
        pkt      = parse_packet(data)
        info     = parse_type1(pkt["payload"])
        conn_id  = info["conn_id"]
        aes_key  = derive_aes_key(leecher_private, dh_public_from_bytes(info["dh_public"]))

        p = build_type4_payload(assembled_hash)
        sock.sendto(
            build_encrypted_packet(verify_port, first_peer["port"], MSG_SEND_HASH, conn_id, p, aes_key),
            (first_peer["ip"], first_peer["port"])
        )
        data, _ = sock.recvfrom(65535)
        pkt     = parse_packet(data)
        result  = parse_encrypted_payload(MSG_CONFIRM_FINISH, pkt["payload"], aes_key)

        if result["success"]:
            print(f"[LEECH] Transfer complete! File saved to {out_path}")
        else:
            print(f"[LEECH] Hash mismatch — file may be corrupted")
    except socket.timeout:
        print(f"[LEECH] Hash verification timed out (file saved anyway)")
    finally:
        sock.close()