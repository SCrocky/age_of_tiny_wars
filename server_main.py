"""
Age of Wars — dedicated game server.

Usage:
    python server_main.py [--scene PATH] [--host HOST] [--port PORT]
                          [--players blue=human,red=ai,...]

If --scene is omitted, a fresh map is generated using the team list from
--players. Default --players is 'blue=human,black=human' (1v1 multiplayer).
"""

import argparse
import asyncio
import os
import sys


_VALID_ROLES = ("human", "ai")


def _parse_players_arg(arg: str) -> list[tuple[str, str]]:
    """
    Parse 'blue=human,red=ai,...' into [('blue','human'), ('red','ai'), ...].
    Validates teams, roles, uniqueness, and supported seat count.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "map_editor"))
    from entities.teams import TEAM_COLORS
    import create_map as _cm

    seats: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in arg.split(","):
        token = raw.strip()
        if "=" not in token:
            raise SystemExit(f"--players: bad token {token!r}; expected team=role")
        team, role = (s.strip() for s in token.split("=", 1))
        if team not in TEAM_COLORS:
            raise SystemExit(
                f"--players: unknown team {team!r}; valid: {', '.join(TEAM_COLORS)}"
            )
        if role not in _VALID_ROLES:
            raise SystemExit(
                f"--players: unknown role {role!r}; valid: {', '.join(_VALID_ROLES)}"
            )
        if team in seen:
            raise SystemExit(f"--players: duplicate team {team!r}")
        seen.add(team)
        seats.append((team, role))

    if len(seats) not in _cm.SUPPORTED_PLAYER_COUNTS:
        raise SystemExit(
            f"--players: {len(seats)} seat(s) given; supported counts: "
            f"{_cm.SUPPORTED_PLAYER_COUNTS}"
        )
    return seats


def _generate_scene(spawn_teams: tuple[str, ...], size: str = "large") -> str:
    """Generate a fresh map and return the path to the scene JSON."""
    import json
    import random
    from datetime import datetime
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "map_editor"))
    import create_map as _cm
    import populate_map as _pm

    _cm._configure_size(size)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    maps_dir = os.path.join(os.path.dirname(__file__), "map_editor", "maps")
    os.makedirs(maps_dir, exist_ok=True)
    stem  = os.path.join(maps_dir, f"map_{stamp}")
    seed  = random.randrange(2 ** 32)
    rng   = random.Random(seed)

    grid              = _cm.make_grid()
    zones             = _cm.assign_zones(rng, spawn_teams)
    resources, spawns = _cm.place_resources(rng, zones, grid)
    map_data          = _cm.build_output(grid, zones, resources, spawns, seed, size)
    buildings, units  = _pm.populate(map_data)
    scene             = _pm.build_scene(map_data, buildings, units, stem)

    scene_path = stem + "_scene.json"
    with open(scene_path, "w") as f:
        json.dump(scene, f, separators=(",", ":"))
    return scene_path


def _validate_scene_matches_seats(scene_path: str,
                                  seats: list[tuple[str, str]]) -> None:
    import json
    from entities.teams import teams_from_scene
    with open(scene_path) as f:
        scene = json.load(f)
    scene_teams = set(teams_from_scene(scene))
    seat_teams  = {team for team, _ in seats}
    if scene_teams != seat_teams:
        raise SystemExit(
            f"--players teams {sorted(seat_teams)} do not match scene teams "
            f"{sorted(scene_teams)} in {scene_path}"
        )


async def main(scene_path: str, host: str, port: int,
               seats: list[tuple[str, str]], udp_port: int | None = None):
    import json
    from network.lobby import wait_for_humans
    from network.server import GameServer
    from network.ai_player import AIPlayer

    with open(scene_path) as f:
        scene = json.load(f)

    human_teams = [team for team, role in seats if role == "human"]
    ai_teams    = [team for team, role in seats if role == "ai"]

    # Spin up AIs first — their reader/writer are in-memory and ready immediately.
    ais: list[AIPlayer] = []
    ai_tasks: list[asyncio.Task] = []
    for team in ai_teams:
        ai = AIPlayer(team, scene)
        ais.append(ai)
        ai_tasks.append(asyncio.create_task(ai.run()))

    humans = await wait_for_humans(host, port, scene_path, human_teams,
                                   udp_port=udp_port)

    players = list(humans) + [(ai.reader, ai.writer, ai.team) for ai in ais]

    server = GameServer(scene_path)
    print(f"[server] Starting game — {len(humans)} human(s), {len(ais)} AI(s)")
    try:
        await server.run(players, udp_port=udp_port)
    finally:
        for t in ai_tasks:
            t.cancel()
    print("[server] Game over.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Age of Wars server")
    parser.add_argument("--scene", default=None, help="Path to scene JSON")
    parser.add_argument("--size",  default="large", choices=["small", "medium", "large"],
                        help="Map size when generating a fresh map (default: large)")
    parser.add_argument("--host",  default="0.0.0.0")
    parser.add_argument("--port",     default=9876, type=int)
    parser.add_argument("--udp-port", default=None, type=int,
                        help="UDP port for snapshot delivery (default: TCP port + 1)")
    parser.add_argument(
        "--players", default="blue=human,black=human",
        help="Comma-separated team=role pairs (2–5 seats), e.g. "
             "'blue=human,red=ai,yellow=human'. "
             "Roles: human, ai. Teams: blue, red, yellow, purple, black.",
    )
    args = parser.parse_args()

    seats = _parse_players_arg(args.players)
    teams = tuple(team for team, _ in seats)

    import collision_masks
    collision_masks.ensure_built()

    scene = args.scene
    if scene is None:
        print(f"[server] Generating {args.size} map for teams: {teams}…")
        scene = _generate_scene(teams, args.size)
        print(f"[server] Scene: {scene}")
    else:
        _validate_scene_matches_seats(scene, seats)

    udp_port = args.udp_port if args.udp_port is not None else args.port + 1
    asyncio.run(main(scene, args.host, args.port, seats, udp_port=udp_port))
