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
import msgpack


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

    def send_snapshot(self, team: str, data: bytes):
        """Send a raw msgpack snapshot datagram to the given team."""
        addr = self._clients.get(team)
        if addr and self._transport:
            try:
                self._transport.sendto(data, addr)
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
