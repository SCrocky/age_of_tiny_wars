"""
Async TCP client for Age of Wars multiplayer.

Wire framing: every message is prefixed with a 4-byte big-endian length.
"""

import asyncio
import struct

import msgpack


class GameClient:
    def __init__(self):
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self, host: str, port: int) -> tuple[str, dict]:
        """
        Connect to the server and wait for GAME_START.
        Returns (player_team, scene_data_dict).
        """
        self._reader, self._writer = await asyncio.open_connection(host, port)
        msg = await self._read_frame()
        assert msg["type"] == "GAME_START", f"Expected GAME_START, got {msg['type']}"
        import json
        scene = json.loads(msg["scene_json"])
        return msg["player_team"], scene

    async def send_command(self, cmd: dict):
        """Serialize and send a command dict to the server."""
        if self._writer is None or self._writer.is_closing():
            return
        payload = msgpack.packb(cmd, use_bin_type=True)
        framed  = struct.pack(">I", len(payload)) + payload
        self._writer.write(framed)
        try:
            await self._writer.drain()
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass

    async def receive_loop(self, on_message):
        """
        Read frames from the server and call on_message(dict) for each.
        Returns when the connection closes.
        """
        while True:
            msg = await self._read_frame()
            if msg is None:
                return
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
