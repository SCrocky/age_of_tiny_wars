"""
Async TCP client for Age of Wars multiplayer.

Wire framing: every message is prefixed with a 4-byte big-endian length.
"""

import asyncio
import struct

import msgpack

from network.serialization import encode_frame


class GameClient:
    def __init__(self):
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._udp_transport: asyncio.DatagramTransport | None = None
        self._udp_queue: asyncio.Queue = asyncio.Queue()

    async def connect(self, host: str, port: int) -> tuple[str, dict]:
        """
        Connect to the server and wait for GAME_START.
        Returns (player_team, scene_data_dict).

        If GAME_START includes 'udp_port' and 'udp_nonce', also opens a local
        UDP socket and sends UDP_HELLO so the server can register our address
        for snapshot delivery.
        """
        self._reader, self._writer = await asyncio.open_connection(host, port)
        msg = await self._read_frame()
        if msg is None or msg.get("type") != "GAME_START":
            raise ValueError(f"Expected GAME_START, got {msg!r}")
        import json
        scene = json.loads(msg["scene_json"])

        udp_port  = msg.get("udp_port")
        udp_nonce = msg.get("udp_nonce")
        if udp_port is not None and udp_nonce:
            await self._setup_udp(host, udp_port, udp_nonce)

        return msg["player_team"], scene

    async def _setup_udp(self, host: str, server_udp_port: int, nonce: str):
        """Open a local UDP socket and send UDP_HELLO to the server."""
        from network.udp import ClientUDPProtocol
        loop = asyncio.get_running_loop()
        protocol = ClientUDPProtocol(self._udp_queue)
        try:
            transport, _ = await loop.create_datagram_endpoint(
                lambda: protocol,
                local_addr=("0.0.0.0", 0),  # OS assigns a port
            )
            self._udp_transport = transport
            hello = msgpack.packb({"type": "UDP_HELLO", "nonce": nonce},
                                  use_bin_type=True)
            transport.sendto(hello, (host, server_udp_port))
        except OSError as e:
            print(f"[client] UDP setup failed ({e}), snapshots will arrive via TCP")

    async def send_command(self, cmd: dict):
        """Serialize and send a command dict to the server over TCP."""
        if self._writer is None or self._writer.is_closing():
            return
        self._writer.write(encode_frame(cmd))
        try:
            await self._writer.drain()
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass

    async def receive_loop(self, on_message):
        """
        Read frames from the server over TCP and call on_message(dict) for each.
        Non-snapshot messages (GAME_OVER, SAVE_OK, DISCONNECTED…) still travel
        over TCP; snapshots will arrive via receive_udp_loop once UDP is set up.
        Returns when the connection closes.
        """
        while True:
            msg = await self._read_frame()
            if msg is None:
                return
            on_message(msg)

    async def receive_udp_loop(self, on_message):
        """
        Deliver incoming UDP snapshot datagrams to on_message.
        Skips datagrams that arrive out of order (older tick than last seen).
        Returns when the UDP socket is closed (None sentinel from protocol).
        """
        from network.udp import FragmentReassembler

        reassembler = FragmentReassembler()
        last_tick = -1
        while True:
            data = await self._udp_queue.get()
            if data is None:
                return
            payload = reassembler.feed(data)
            if payload is None:
                continue  # incomplete snapshot — wait for more fragments
            try:
                msg = msgpack.unpackb(payload, raw=False)
            except Exception:
                continue
            tick = msg.get("tick", -1)
            if tick <= last_tick:
                continue  # out-of-order or duplicate — discard
            last_tick = tick
            on_message(msg)

    async def _read_frame(self) -> dict | None:
        try:
            header = await self._reader.readexactly(4)
        except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
            return None
        length = struct.unpack(">I", header)[0]
        try:
            payload = await self._reader.readexactly(length)
        except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
            return None
        return msgpack.unpackb(payload, raw=False)

    def close(self):
        if self._writer:
            self._writer.close()
        if self._udp_transport:
            self._udp_transport.close()
