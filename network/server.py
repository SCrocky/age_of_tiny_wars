"""
Authoritative game server.

Runs the full game simulation headlessly and broadcasts state snapshots at
10 Hz over TCP.  Clients send length-prefixed msgpack command messages; the
server applies them on the next available tick.

Wire framing: every message (both directions) is prefixed with a 4-byte
big-endian unsigned integer giving the payload length.
"""

import asyncio
import math
import struct
import time

from game import Game
from map import TILE_SIZE
from entities.building import Castle, Tower
from entities.archer import Archer
from entities.warrior import Warrior
from systems.pathfinding import astar
from network.serialization import serialize_snapshot, deserialize_command

TICK_RATE      = 60       # game simulation Hz
SNAPSHOT_RATE  = 10       # state broadcasts per second
_TICKS_PER_SNAP = TICK_RATE // SNAPSHOT_RATE


async def _read_frame(reader: asyncio.StreamReader) -> bytes | None:
    """Read one length-prefixed frame.  Returns None on EOF/error."""
    try:
        header = await reader.readexactly(4)
    except (asyncio.IncompleteReadError, ConnectionResetError):
        return None
    length = struct.unpack(">I", header)[0]
    try:
        return await reader.readexactly(length)
    except (asyncio.IncompleteReadError, ConnectionResetError):
        return None


RECONNECT_TIMEOUT = 30.0  # seconds to wait for reconnect before forfeiting


class GameServer:
    def __init__(self, scene_path: str):
        self.game = Game(scene_path)
        self._tick: int = 0
        self._command_queue: asyncio.Queue = asyncio.Queue()
        self._writers: dict[str, asyncio.StreamWriter] = {}
        self._disconnected: set[str] = set()
        self._paused: bool = False
        self._pending_garrisons: dict[int, object] = {}  # archer entity_id → Tower

    async def run(self, players: list):
        """
        `players` is the list of (reader, writer, team) returned by lobby.
        Starts the game loop and per-client read loops concurrently.
        """
        for reader, writer, team in players:
            self._writers[team] = writer

        client_tasks = [
            asyncio.create_task(self._client_reader(reader, team))
            for reader, writer, team in players
        ]
        loop_task = asyncio.create_task(self._game_loop())

        await asyncio.gather(loop_task, *client_tasks)

    # ------------------------------------------------------------------
    # Game loop
    # ------------------------------------------------------------------

    async def _game_loop(self):
        dt = 1.0 / TICK_RATE
        next_tick_time = time.monotonic()

        while True:
            now = time.monotonic()
            sleep = next_tick_time - now
            if sleep > 0:
                await asyncio.sleep(sleep)
            next_tick_time += dt

            if self._paused:
                await asyncio.sleep(dt)
                next_tick_time = time.monotonic()  # don't pile up ticks while paused
                continue

            # Drain all pending commands before this tick
            while not self._command_queue.empty():
                cmd, player_team = self._command_queue.get_nowait()
                self._apply_command(cmd, player_team)

            self.game.update(dt)
            self._resolve_pending_garrisons()
            self._tick += 1

            if self._tick % _TICKS_PER_SNAP == 0:
                await self._broadcast_snapshot()
                winner = self._check_victory()
                if winner:
                    await self._broadcast({"type": "GAME_OVER", "winner": winner})
                    break

    # ------------------------------------------------------------------
    # Snapshot broadcast
    # ------------------------------------------------------------------

    async def _broadcast_snapshot(self):
        data = serialize_snapshot(self.game, self._tick)
        await self._send_all(data)

    async def _broadcast(self, obj: dict):
        import msgpack
        payload = msgpack.packb(obj, use_bin_type=True)
        framed = struct.pack(">I", len(payload)) + payload
        await self._send_all(framed)

    async def _send_all(self, data: bytes):
        dead = []
        for team, writer in self._writers.items():
            try:
                writer.write(data)
                await writer.drain()
            except (ConnectionResetError, BrokenPipeError, OSError):
                dead.append(team)
        for team in dead:
            self._handle_disconnect(team)

    # ------------------------------------------------------------------
    # Client reader
    # ------------------------------------------------------------------

    async def _client_reader(self, reader: asyncio.StreamReader, team: str):
        while True:
            payload = await _read_frame(reader)
            if payload is None:
                self._handle_disconnect(team)
                return
            try:
                cmd = deserialize_command(payload)
                await self._command_queue.put((cmd, team))
            except Exception as e:
                print(f"[server] bad command from {team}: {e}")

    def _handle_disconnect(self, team: str):
        if team not in self._disconnected:
            self._disconnected.add(team)
            print(f"[server] {team} disconnected — pausing game for {RECONNECT_TIMEOUT}s")
            self._writers.pop(team, None)
            self._paused = True
            asyncio.create_task(self._reconnect_timeout(team))

    async def _reconnect_timeout(self, team: str):
        deadline = time.monotonic() + RECONNECT_TIMEOUT
        while time.monotonic() < deadline:
            await asyncio.sleep(1)
            if team not in self._disconnected:
                print(f"[server] {team} reconnected — resuming")
                return
        print(f"[server] {team} did not reconnect — forfeiting")
        other = "black" if team == "blue" else "blue"
        await self._broadcast({"type": "GAME_OVER", "winner": other})

    # ------------------------------------------------------------------
    # Pending garrison resolution
    # ------------------------------------------------------------------

    def _resolve_pending_garrisons(self):
        done = []
        for archer_id, tower in self._pending_garrisons.items():
            archer = next((u for u in self.game.units if u.entity_id == archer_id), None)
            if archer is None or not archer.alive or not tower.alive:
                done.append(archer_id)
                continue
            tx, ty = tower.closest_point(archer.x, archer.y)
            if math.hypot(tx - archer.x, ty - archer.y) <= TILE_SIZE:
                if tower.garrison(archer):
                    self.game.units.remove(archer)
                done.append(archer_id)
            elif archer.attack_target is None:
                archer._navigate_to(tx, ty, self.game.map, TILE_SIZE)
        for archer_id in done:
            del self._pending_garrisons[archer_id]

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    def _apply_command(self, cmd: dict, player_team: str):
        kind = cmd.get("type")

        if kind == "CMD_MOVE":
            ids = set(cmd.get("unit_ids", []))
            goal_col = cmd.get("goal_col", 0)
            goal_row = cmd.get("goal_row", 0)
            all_movable = self.game.units + self.game.pawns
            targets = [u for u in all_movable if u.entity_id in ids and u.team == player_team]
            offsets = self.game._formation_offsets(len(targets))
            for unit, (dc, dr) in zip(targets, offsets):
                dest = self.game.map.nearest_walkable(goal_col + dc, goal_row + dr)
                start = (int(unit.x // TILE_SIZE), int(unit.y // TILE_SIZE))
                path = astar(self.game.map, start, dest)
                unit.set_path(path)
                self._pending_garrisons.pop(unit.entity_id, None)

        elif kind == "CMD_ATTACK":
            ids = set(cmd.get("unit_ids", []))
            target_id = cmd.get("target_id")
            target = self._find_entity(target_id)
            if target is None:
                return
            enemy_pool = [e for e in self.game.units + self.game.pawns + self.game.buildings
                          if e.team != player_team]
            for u in self.game.units:
                if u.entity_id in ids and u.team == player_team:
                    u.set_attack_target(target, enemy_pool)
                    self._pending_garrisons.pop(u.entity_id, None)

        elif kind == "CMD_GATHER":
            ids = set(cmd.get("pawn_ids", []))
            resource_id = cmd.get("resource_id")
            resource = self._find_resource(resource_id)
            if resource is None or resource.depleted:
                return
            for p in self.game.pawns:
                if p.entity_id in ids and p.team == player_team:
                    p.assign_gather(resource, self.game.buildings, self.game.resources)

        elif kind == "CMD_SPAWN":
            building_id = cmd.get("building_id")
            unit_type = cmd.get("unit_type", "")
            building = self._find_building(building_id, player_team)
            if building is None:
                return
            self._do_spawn(unit_type, building, player_team)

        elif kind == "CMD_BUILD":
            pawn_ids = set(cmd.get("pawn_ids", []))
            building_type = cmd.get("building_type", "")
            wx = cmd.get("world_x", 0.0)
            wy = cmd.get("world_y", 0.0)
            self._do_build(building_type, wx, wy, pawn_ids, player_team)

        elif kind == "CMD_GARRISON":
            archer_ids = set(cmd.get("archer_ids", []))
            tower_id   = cmd.get("tower_id")
            tower = next(
                (b for b in self.game.buildings
                 if b.entity_id == tower_id and b.team == player_team
                 and isinstance(b, Tower) and b.alive),
                None,
            )
            if tower is None:
                return
            for u in list(self.game.units):
                if u.entity_id in archer_ids and u.team == player_team and isinstance(u, Archer):
                    tx, ty = tower.closest_point(u.x, u.y)
                    if math.hypot(tx - u.x, ty - u.y) <= TILE_SIZE:
                        if tower.garrison(u):
                            self.game.units.remove(u)
                            self._pending_garrisons.pop(u.entity_id, None)
                    else:
                        u._navigate_to(tx, ty, self.game.map, TILE_SIZE)
                        self._pending_garrisons[u.entity_id] = tower
                    break  # one archer per tower

        elif kind == "CMD_RELEASE":
            tower_id = cmd.get("tower_id")
            tower = next(
                (b for b in self.game.buildings
                 if b.entity_id == tower_id and b.team == player_team
                 and isinstance(b, Tower) and b.alive),
                None,
            )
            if tower is None:
                return
            archer = tower.release_archer()
            if archer is not None:
                self.game.units.append(archer)

        elif kind == "CMD_DEV_SPAWN":
            wx = cmd.get("world_x", 0.0)
            wy = cmd.get("world_y", 0.0)
            unit = self.game._assign_id(Warrior(wx, wy, team=player_team))
            unit.hp = unit.max_hp // 2
            self.game.units.append(unit)

        elif kind == "CMD_ASSIGN_BUILD":
            pawn_ids     = set(cmd.get("pawn_ids", []))
            blueprint_id = cmd.get("blueprint_id")
            bp = next((b for b in self.game.blueprints
                       if b.entity_id == blueprint_id and b.alive), None)
            if bp is None:
                return
            for p in self.game.pawns:
                if p.entity_id in pawn_ids and p.team == player_team:
                    p.assign_build(bp, self.game.blueprints)

    # ------------------------------------------------------------------
    # Spawn helpers
    # ------------------------------------------------------------------

    def _do_spawn(self, unit_type: str, building, team: str):
        if unit_type in self.game._SPAWN_TABLE:
            self.game._spawn_unit(unit_type, team=team, building=building)

    def _do_build(self, building_type: str, wx: float, wy: float, pawn_ids: set, team: str):
        from entities.blueprint import Blueprint, BUILDABLE
        cls_costs = BUILDABLE.get(building_type)
        if cls_costs is None:
            return
        cls, costs = cls_costs
        eco = self.game.economy[team]
        if not all(eco.get(k, 0) >= v for k, v in costs.items()):
            return
        for k, v in costs.items():
            eco[k] -= v
        building = cls(wx, wy, team=team)
        self.game.map.clear_area(wx, wy, tile_radius=4)
        bp = self.game._assign_id(Blueprint(building))
        self.game.blueprints.append(bp)
        for pawn in self.game.pawns:
            if pawn.entity_id in pawn_ids and pawn.team == team:
                pawn.assign_build(bp, self.game.blueprints)

    # ------------------------------------------------------------------
    # Entity lookup
    # ------------------------------------------------------------------

    def _find_entity(self, entity_id: int):
        for lst in (self.game.units, self.game.pawns, self.game.buildings):
            for e in lst:
                if e.entity_id == entity_id:
                    return e
        return None

    def _find_resource(self, entity_id: int):
        for r in self.game.resources:
            if r.entity_id == entity_id:
                return r
        return None

    def _find_building(self, entity_id: int, team: str):
        for b in self.game.buildings:
            if b.entity_id == entity_id and b.team == team and b.alive:
                return b
        return None

    # ------------------------------------------------------------------
    # Victory
    # ------------------------------------------------------------------

    def _check_victory(self) -> str | None:
        blue_alive  = any(b for b in self.game.buildings if b.team == "blue"  and isinstance(b, Castle) and b.alive)
        black_alive = any(b for b in self.game.buildings if b.team == "black" and isinstance(b, Castle) and b.alive)
        if not blue_alive:
            return "black"
        if not black_alive:
            return "blue"
        return None
