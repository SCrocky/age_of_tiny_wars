"""
Pre-game lobby: waits for the configured number of human clients, assigns each
to a team in connection order, and fires GAME_START.
"""

import asyncio
import json

from network.serialization import encode_frame


async def wait_for_humans(host: str, port: int, scene_path: str,
                          human_teams: list[str], udp_port: int | None = None):
    """
    Start a TCP server and wait for `len(human_teams)` clients.

    Connection order maps to `human_teams` order: the first connection becomes
    `human_teams[0]`, the second `human_teams[1]`, and so on. Once all human
    seats are filled, GAME_START is sent to every client.

    Returns a list of (reader, writer, team, nonce) tuples in connection order.
    `nonce` is the per-player secret used to match the client's UDP_HELLO.
    If `human_teams` is empty (e.g. all-AI match), returns immediately.
    """
    if not human_teams:
        return []

    import os

    players: list[tuple[asyncio.StreamReader, asyncio.StreamWriter, str, str]] = []
    ready = asyncio.Event()

    with open(scene_path) as f:
        scene_data = json.load(f)
    scene_json = json.dumps(scene_data).encode()

    async def _handle(reader, writer):
        idx = len(players)
        if idx >= len(human_teams):
            writer.close()
            return
        team  = human_teams[idx]
        nonce = os.urandom(16).hex()
        players.append((reader, writer, team, nonce))
        print(f"[lobby] Player {idx + 1}/{len(human_teams)} connected → team={team}")
        if len(players) == len(human_teams):
            ready.set()

    server = await asyncio.start_server(_handle, host, port)
    addr = server.sockets[0].getsockname()
    print(f"[lobby] Listening on {addr[0]}:{addr[1]} — "
          f"waiting for {len(human_teams)} player(s)…")

    await ready.wait()
    server.close()  # stop accepting new connections; existing ones stay open

    # Send GAME_START to every human simultaneously.
    start_tasks = []
    for reader, writer, team, nonce in players:
        payload = {"type": "GAME_START", "player_team": team, "scene_json": scene_json}
        if udp_port is not None:
            payload["udp_port"]  = udp_port
            payload["udp_nonce"] = nonce
        writer.write(encode_frame(payload))
        start_tasks.append(writer.drain())
    await asyncio.gather(*start_tasks)

    print(f"[lobby] GAME_START sent to {len(players)} player(s).")
    # Return as (reader, writer, team) for backward compat; nonce is only needed
    # by the server to register with the UDP protocol.
    return players
