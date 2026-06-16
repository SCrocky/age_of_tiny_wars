"""
In-process AI player.

Replaces a TCP (reader, writer, team) triple with an in-memory pair so the
AI can slot directly into GameServer.run() without a network connection.

Server calls write_snapshot(dict) on the writer (_SnapshotSink) directly,
bypassing msgpack encode/decode for in-process snapshots.
The AI feeds length-prefixed msgpack frames into the reader (StreamReader) for commands.
"""

import asyncio
import struct

import msgpack

from network.serialization import encode_frame

from ai.bot import BotAI


class _SnapshotSink:
    """
    Fake asyncio.StreamWriter.

    Accumulates bytes written by the server, parses complete msgpack frames,
    and forwards GAME_STATE messages to an asyncio.Queue.
    """

    def __init__(self):
        self._buf   = b""
        self.queue: asyncio.Queue = asyncio.Queue()

    def write(self, data: bytes) -> None:
        self._buf += data
        while len(self._buf) >= 4:
            (length,) = struct.unpack_from(">I", self._buf)
            if len(self._buf) < 4 + length:
                break
            payload       = self._buf[4:4 + length]
            self._buf     = self._buf[4 + length:]
            try:
                msg = msgpack.unpackb(payload, raw=False)
                if msg.get("type") == "GAME_STATE":
                    self.queue.put_nowait(msg)
            except Exception:
                pass

    def write_snapshot(self, msg: dict) -> None:
        """Bypass msgpack for in-process snapshots — put the dict directly."""
        if msg.get("type") == "GAME_STATE":
            self.queue.put_nowait(msg)

    async def drain(self) -> None:
        pass

    def is_closing(self) -> bool:
        return False

    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


class AIPlayer:
    """
    Connects a BotAI to the server's player slot without TCP.

    Usage:
        ai = AIPlayer("black", scene)
        players = [human_player, (ai.reader, ai.writer, ai.team)]
        ai_task = asyncio.create_task(ai.run())
        await server.run(players)
        ai_task.cancel()
    """

    def __init__(self, team: str, scene: dict):
        self.team   = team
        self.reader = asyncio.StreamReader()  # server reads AI commands from here
        self.writer = _SnapshotSink()         # server writes snapshots here

        self._bot = BotAI(team, scene["cols"], scene["rows"])

    async def run(self) -> None:
        """Decision loop — run as a sibling task alongside the server's game loop."""
        while True:
            snap = await self.writer.queue.get()
            # Discard stale snapshots if we've fallen behind
            while not self.writer.queue.empty():
                snap = self.writer.queue.get_nowait()

            for cmd in self._bot.apply_snapshot(snap):
                self._feed(cmd)

    def _feed(self, cmd: dict) -> None:
        self.reader.feed_data(encode_frame(cmd))
