"""
Pre-game lobby: waits for exactly 2 TCP clients, assigns teams, fires GAME_START.
Also provides accept_reconnect() for handling mid-game reconnections.
"""

import asyncio
import json
import struct

import msgpack


TEAMS = ["blue", "black"]


async def wait_for_players(host: str, port: int, scene_path: str):
    """
    Start a TCP server, wait for 2 clients, assign teams.
    Returns list of (reader, writer, team) tuples once both connect.
    """
    players = []
    ready = asyncio.Event()

    with open(scene_path) as f:
        scene_json = json.dumps(json.load(f)).encode()

    async def _handle(reader, writer):
        idx = len(players)
        if idx >= 2:
            writer.close()
            return
        team = TEAMS[idx]
        players.append((reader, writer, team))
        print(f"[lobby] Player {idx + 1} connected → team={team}")
        if len(players) == 2:
            ready.set()

    server = await asyncio.start_server(_handle, host, port)
    addr = server.sockets[0].getsockname()
    print(f"[lobby] Listening on {addr[0]}:{addr[1]} — waiting for 2 players…")

    await ready.wait()
    server.close()  # stop accepting new connections; existing ones stay open

    # Send GAME_START to both players simultaneously
    start_tasks = []
    for reader, writer, team in players:
        msg = msgpack.packb({
            "type":        "GAME_START",
            "player_team": team,
            "scene_json":  scene_json,
        }, use_bin_type=True)
        framed = struct.pack(">I", len(msg)) + msg
        writer.write(framed)
        start_tasks.append(writer.drain())
    await asyncio.gather(*start_tasks)

    print("[lobby] GAME_START sent to both players.")
    return players


async def wait_for_one_player(host: str, port: int, scene_path: str):
    """
    Solo mode: wait for a single human player (assigned 'blue') and return
    their (reader, writer, team) tuple. The AI takes the remaining team.
    """
    player = None
    ready  = asyncio.Event()

    with open(scene_path) as f:
        scene_json = json.dumps(json.load(f)).encode()

    async def _handle(reader, writer):
        nonlocal player
        if player is not None:
            writer.close()
            return
        player = (reader, writer, "blue")
        print("[lobby] Human player connected → team=blue")
        ready.set()

    server = await asyncio.start_server(_handle, host, port)
    addr   = server.sockets[0].getsockname()
    print(f"[lobby] Listening on {addr[0]}:{addr[1]} — solo mode, waiting for 1 player…")

    await ready.wait()
    server.close()

    reader, writer, team = player
    msg    = msgpack.packb({"type": "GAME_START", "player_team": team,
                             "scene_json": scene_json}, use_bin_type=True)
    framed = struct.pack(">I", len(msg)) + msg
    writer.write(framed)
    await writer.drain()

    print("[lobby] GAME_START sent to human player.")
    return player
