"""
UDP transport helpers for snapshot delivery.

The server sends snapshots over UDP (unreliable/unordered) to avoid TCP
head-of-line blocking.  Commands still travel over TCP (reliable/ordered).

Protocol
--------
1. Server opens a UDP socket on TCP_PORT + 1.
2. `GAME_START` includes "udp_port" and a per-player "udp_nonce".
3. After receiving GAME_START the client opens a local UDP socket and sends a
   UDP_HELLO datagram (containing the nonce) to the server's UDP endpoint.
4. Server maps the nonce to a team and records the client's (ip, port).
5. Subsequent snapshots are sent as raw msgpack-encoded UDP datagrams.
   The client skips any that arrive out of order (older tick than last seen).
"""

import asyncio
import struct

import msgpack


# ---------------------------------------------------------------------------
# Snapshot fragmentation
# ---------------------------------------------------------------------------
# A full keyframe snapshot easily exceeds the path MTU (and can exceed the
# 65507-byte UDP datagram ceiling), which made the kernel drop it with
# EMSGSIZE.  We split every snapshot into MTU-sized datagrams, each tagged with
# (msg_id, chunk_index, chunk_count) so the client can reassemble.  A datagram
# carries the *raw* msgpack payload — never the TCP length-prefixed frame, since
# datagrams are already self-delimiting.

_FRAG_HEADER = struct.Struct(">IHH")   # msg_id (u32), chunk_index (u16), count (u16)
# Payload bytes per datagram. 1200 keeps header(8) + UDP(8) + IP(20) well under
# a conservative 1400-byte MTU, so IP-layer fragmentation never kicks in.
_FRAG_CHUNK = 1200


def pack_fragments(msg_id: int, payload: bytes) -> list[bytes]:
    """Split a raw msgpack payload into reassembly-tagged datagrams."""
    if not payload:
        return []
    count = (len(payload) + _FRAG_CHUNK - 1) // _FRAG_CHUNK
    if count > 0xFFFF:
        raise ValueError(f"snapshot needs {count} fragments (>65535)")
    mid = msg_id & 0xFFFFFFFF
    out = []
    for i in range(count):
        chunk = payload[i * _FRAG_CHUNK:(i + 1) * _FRAG_CHUNK]
        out.append(_FRAG_HEADER.pack(mid, i, count) + chunk)
    return out


class FragmentReassembler:
    """Reassemble fragmented snapshot datagrams on the client.

    Snapshots are time-sensitive, so only the most recent in-progress message is
    buffered: when fragments of a newer msg_id start arriving we abandon any
    older partial (a dropped fragment just costs us one snapshot, which the next
    keyframe heals).  Stale fragments from a superseded message are ignored.
    """

    def __init__(self):
        self._msg_id: int | None = None
        self._count: int = 0
        self._chunks: dict[int, bytes] = {}

    def feed(self, datagram: bytes) -> bytes | None:
        """Return the full payload bytes once all fragments are present, else None."""
        if len(datagram) < _FRAG_HEADER.size:
            return None
        msg_id, index, count = _FRAG_HEADER.unpack_from(datagram)
        chunk = datagram[_FRAG_HEADER.size:]

        if count <= 1:
            return chunk  # single-datagram snapshot — no buffering needed

        if msg_id != self._msg_id:
            if self._msg_id is not None and msg_id < self._msg_id:
                return None  # late fragment for an already-superseded snapshot
            self._msg_id = msg_id
            self._count = count
            self._chunks = {}

        self._chunks[index] = chunk
        if len(self._chunks) == self._count:
            payload = b"".join(self._chunks[i] for i in range(self._count))
            self._msg_id = None
            self._chunks = {}
            return payload
        return None


class ServerUDPProtocol(asyncio.DatagramProtocol):
    """Asyncio DatagramProtocol that lives on the server's UDP socket."""

    def __init__(self):
        self._transport: asyncio.DatagramTransport | None = None
        # nonce → team, populated before GAME_START is sent
        self._pending: dict[str, str] = {}
        # team → (ip, port)
        self._clients: dict[str, tuple[str, int]] = {}

    # ------------------------------------------------------------------
    # asyncio DatagramProtocol callbacks
    # ------------------------------------------------------------------

    def connection_made(self, transport: asyncio.DatagramTransport):
        self._transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]):
        try:
            msg = msgpack.unpackb(data, raw=False)
        except Exception:
            return
        if msg.get("type") == "UDP_HELLO":
            nonce = msg.get("nonce")
            if nonce and nonce in self._pending:
                team = self._pending.pop(nonce)
                self._clients[team] = addr
                print(f"[udp] {team} registered from {addr[0]}:{addr[1]}")

    def error_received(self, exc: Exception):
        print(f"[udp] error: {exc}")

    # ------------------------------------------------------------------
    # Server-side helpers
    # ------------------------------------------------------------------

    def register_nonce(self, nonce: str, team: str):
        """Called before GAME_START so we can match the incoming hello."""
        self._pending[nonce] = team

    def send_snapshot(self, team: str, msg_id: int, payload: bytes):
        """Fragment a raw msgpack snapshot payload and send it to the given team.

        `payload` is the bare msgpack bytes (no TCP length prefix). `msg_id`
        identifies this snapshot for client-side reassembly (the tick works
        well: monotonic and unique per snapshot)."""
        addr = self._clients.get(team)
        if not (addr and self._transport):
            return
        try:
            fragments = pack_fragments(msg_id, payload)
        except ValueError as exc:
            print(f"[udp] {exc}; dropping snapshot")
            return
        for dg in fragments:
            try:
                self._transport.sendto(dg, addr)
            except (OSError, RuntimeError):
                pass

    def remove_client(self, team: str):
        self._clients.pop(team, None)

    def has_client(self, team: str) -> bool:
        return team in self._clients


class ClientUDPProtocol(asyncio.DatagramProtocol):
    """Asyncio DatagramProtocol that lives on the client's UDP socket."""

    def __init__(self, queue: asyncio.Queue):
        self._queue = queue
        self._transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.DatagramTransport):
        self._transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]):
        self._queue.put_nowait(data)

    def error_received(self, exc: Exception):
        pass

    def connection_lost(self, exc):
        self._queue.put_nowait(None)  # signal EOF
