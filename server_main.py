"""
Age of Wars — dedicated game server.

Usage:
    python server_main.py [--scene PATH] [--host HOST] [--port PORT]

If --scene is omitted, a fresh map is generated.
"""

import argparse
import asyncio
import os
import sys


def _generate_scene() -> str:
    """Generate a fresh map and return the path to the scene JSON."""
    import json
    import random
    from datetime import datetime
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "map_editor"))
    import create_map as _cm
    import populate_map as _pm

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem  = os.path.join(os.path.dirname(__file__), "map_editor", "maps", f"map_{stamp}")
    seed  = random.randrange(2 ** 32)
    rng   = random.Random(seed)

    grid              = _cm.make_grid()
    zones             = _cm.assign_zones(rng)
    resources, spawns = _cm.place_resources(rng, zones, grid)
    map_data          = _cm.build_output(grid, zones, resources, spawns, seed)
    buildings, units  = _pm.populate(map_data)
    scene             = _pm.build_scene(map_data, buildings, units, stem)

    scene_path = stem + "_scene.json"
    with open(scene_path, "w") as f:
        json.dump(scene, f, separators=(",", ":"))
    return scene_path


async def main(scene_path: str, host: str, port: int):
    from network.lobby import wait_for_players
    from network.server import GameServer

    players = await wait_for_players(host, port, scene_path)
    server  = GameServer(scene_path)
    print("[server] Starting game…")
    await server.run(players)
    print("[server] Game over.")


async def main_solo(scene_path: str, host: str, port: int):
    import json
    from network.lobby import wait_for_one_player
    from network.server import GameServer
    from network.ai_player import AIPlayer

    with open(scene_path) as f:
        scene = json.load(f)

    human  = await wait_for_one_player(host, port, scene_path)
    ai     = AIPlayer("black", scene)
    ai_task = asyncio.create_task(ai.run())

    server  = GameServer(scene_path)
    print("[server] Starting solo game…")
    try:
        await server.run([human, (ai.reader, ai.writer, ai.team)])
    finally:
        ai_task.cancel()
    print("[server] Game over.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Age of Wars server")
    parser.add_argument("--scene", default=None, help="Path to scene JSON")
    parser.add_argument("--host",  default="0.0.0.0")
    parser.add_argument("--port",  default=9876, type=int)
    parser.add_argument("--solo",  action="store_true",
                        help="Single-player mode: AI controls the black team")
    args = parser.parse_args()

    scene = args.scene
    if scene is None:
        print("[server] Generating map…")
        scene = _generate_scene()
        print(f"[server] Scene: {scene}")

    if args.solo:
        asyncio.run(main_solo(scene, args.host, args.port))
    else:
        asyncio.run(main(scene, args.host, args.port))
