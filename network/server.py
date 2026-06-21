"""
Authoritative game server.

Runs the full game simulation headlessly and broadcasts state snapshots at
20 Hz over UDP (with TCP fallback until the UDP handshake completes).
Clients send length-prefixed msgpack command messages over TCP; the server
applies them on the next available tick.

Wire framing: every message (both directions) is prefixed with a 4-byte
big-endian unsigned integer giving the payload length.
"""

import asyncio
import math
import msgpack
import os
import struct
import time
from datetime import datetime, timezone, timedelta

_UTC = timezone.utc

from game import Game
from map import TILE_SIZE, NAV_TILE
from entities.building import Castle, Tower
from entities.archer import Archer
from entities.warrior import Warrior
from systems.pathfinding import astar
from network.serialization import build_snapshot, build_delta_snapshot, encode_frame, encode_payload, deserialize_command
from network.udp import ServerUDPProtocol

TICK_RATE      = 60       # game simulation Hz
SNAPSHOT_RATE  = 20       # state broadcasts per second
_TICKS_PER_SNAP = TICK_RATE // SNAPSHOT_RATE

# Periodically resend a full snapshot ("keyframe") instead of a delta. Deltas
# travel over unreliable UDP, so a dropped delta would otherwise strand a
# one-shot state change (a unit's final resting position, an hp tick, an
# animation switch) until that entity next changes. Keyframes re-baseline every
# client so any lost state self-heals within this interval.
KEYFRAME_INTERVAL_SEC = 1.0
_SNAPSHOTS_PER_KEYFRAME = max(1, int(SNAPSHOT_RATE * KEYFRAME_INTERVAL_SEC))


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
        self._scene_path = scene_path
        self._tick: int = 0
        self._command_queue: asyncio.Queue = asyncio.Queue()
        self._writers: dict[str, asyncio.StreamWriter] = {}
        self._disconnected: set[str] = set()
        self._paused: bool = False
        self._manually_paused: bool = False
        self._save_pending: str | None = None
        self._pending_garrisons: dict[int, object] = {}  # archer entity_id → Tower
        self._last_save_file: str | None = None
        # Maps team → {entity_id: serialized_dict} from the last snapshot sent.
        # Used to compute per-client delta snapshots.
        self._prev_entities_by_team: dict[str, dict[int, dict]] = {}
        self._udp: ServerUDPProtocol | None = None
        self._udp_port: int | None = None
        self._reconnect_tasks: list[asyncio.Task] = []

    async def run(self, players: list, udp_port: int | None = None):
        """
        `players` is the list of (reader, writer, team[, nonce]) returned by lobby.
        Starts the game loop and per-client read loops concurrently.

        If `udp_port` is given, opens a UDP socket on that port and registers
        each player's nonce so snapshot delivery can switch to UDP once the
        client sends its UDP_HELLO.
        """
        # Open UDP endpoint if requested.
        if udp_port is not None:
            loop = asyncio.get_running_loop()
            self._udp = ServerUDPProtocol()
            try:
                await loop.create_datagram_endpoint(
                    lambda: self._udp,
                    local_addr=("0.0.0.0", udp_port),
                )
                self._udp_port = udp_port
                print(f"[server] UDP snapshot socket on port {udp_port}")
            except OSError as e:
                print(f"[server] UDP unavailable ({e}), falling back to TCP snapshots")
                self._udp = None

        for entry in players:
            reader, writer, team = entry[0], entry[1], entry[2]
            nonce = entry[3] if len(entry) > 3 else None
            self._writers[team] = writer
            if self._udp and nonce:
                self._udp.register_nonce(nonce, team)

        client_tasks = [
            asyncio.create_task(self._client_reader(entry[0], entry[2]))
            for entry in players
        ]
        loop_task = asyncio.create_task(self._game_loop())

        try:
            await loop_task
        finally:
            all_tasks = client_tasks + self._reconnect_tasks
            for task in all_tasks:
                task.cancel()
            await asyncio.gather(*all_tasks, return_exceptions=True)
            self._reconnect_tasks.clear()

    # ------------------------------------------------------------------
    # Game loop
    # ------------------------------------------------------------------

    async def _game_loop(self):
        dt = 1.0 / TICK_RATE
        next_tick_time = time.monotonic()
        _was_paused = False

        while True:
            now = time.monotonic()
            sleep = next_tick_time - now
            if sleep > 0:
                await asyncio.sleep(sleep)
            next_tick_time += dt

            # Always drain commands so pause/save/unpause work while paused too.
            while not self._command_queue.empty():
                cmd, player_team = self._command_queue.get_nowait()
                self._apply_command(cmd, player_team)

            if self._paused:
                _was_paused = True
                next_tick_time = time.monotonic() + dt  # sleep one tick, don't spin
                self._tick += 1
                if self._tick % _TICKS_PER_SNAP == 0:
                    await self._broadcast_snapshot()
                    # Execute a pending save after one paused snapshot so clients
                    # see the overlay before the (potentially slow) file write.
                    if self._save_pending:
                        self.game.save(self._save_pending)
                        self._last_save_file = os.path.basename(self._save_pending)
                        self._save_pending = None
                        if not self._manually_paused:
                            self._paused = False
                continue

            if _was_paused:
                shift = datetime.now(_UTC) - self.game.last_tick_time
                self.game.shift_all_production(shift)
                _was_paused = False

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
        # Serialize entities once; reuse for all clients.
        full_snap = build_snapshot(self.game, self._tick, paused=self._paused)
        entities  = full_snap["entities"]
        current_by_id: dict[int, dict] = {d["id"]: d for d in entities}

        snap_index = self._tick // _TICKS_PER_SNAP
        is_keyframe = (snap_index % _SNAPSHOTS_PER_KEYFRAME == 0)

        # Lazily encode the shared full snapshot, once per transport flavour:
        # raw msgpack payload for UDP (fragmented, self-delimiting), and a
        # length-prefixed frame for TCP.
        full_payload: bytes | None = None
        full_frame:   bytes | None = None
        dead = []

        for team, writer in self._writers.items():
            try:
                if hasattr(writer, "write_snapshot"):
                    # Headless / AI writer — always gets the full dict.
                    writer.write_snapshot(full_snap)
                    continue

                prev = self._prev_entities_by_team.get(team)
                if prev is None or is_keyframe:
                    # First snapshot, or periodic keyframe — send full state so
                    # the client re-baselines and any UDP-dropped delta heals.
                    snap_dict = full_snap
                    is_full = True
                else:
                    snap_dict = build_delta_snapshot(
                        entities, self._tick, prev,
                        self.game.economy, paused=self._paused,
                    )
                    is_full = False

                self._prev_entities_by_team[team] = current_by_id

                # Prefer UDP (fire-and-forget, no HOL blocking).  Fall back to
                # TCP for clients that haven't completed the UDP handshake yet.
                if self._udp and self._udp.has_client(team):
                    if is_full:
                        if full_payload is None:
                            full_payload = encode_payload(full_snap)
                        payload = full_payload
                    else:
                        payload = encode_payload(snap_dict)
                    self._udp.send_snapshot(team, self._tick, payload)
                else:
                    if is_full:
                        if full_frame is None:
                            full_frame = encode_frame(full_snap)
                        encoded = full_frame
                    else:
                        encoded = encode_frame(snap_dict)
                    writer.write(encoded)
                    await writer.drain()

            except (ConnectionResetError, BrokenPipeError, OSError):
                dead.append(team)

        for team in dead:
            self._handle_disconnect(team)

        if self._last_save_file:
            await self._broadcast({"type": "SAVE_OK", "file": self._last_save_file})
            self._last_save_file = None

    async def _broadcast(self, obj: dict):
        await self._send_all(encode_frame(obj))

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
            self._prev_entities_by_team.pop(team, None)  # force full snap on reconnect
            if self._udp:
                self._udp.remove_client(team)
            self._paused = True
            self._reconnect_tasks.append(asyncio.create_task(self._reconnect_timeout(team)))

    async def _reconnect_timeout(self, team: str):
        deadline = time.monotonic() + RECONNECT_TIMEOUT
        while time.monotonic() < deadline:
            await asyncio.sleep(1)
            if team not in self._disconnected:
                print(f"[server] {team} reconnected — resuming")
                return
        print(f"[server] {team} did not reconnect — forfeiting")
        # Destroy the team's Castles so _check_victory eliminates them. With
        # N>2 the remaining teams keep playing until exactly one survives.
        for b in self.game.buildings:
            if b.team == team and isinstance(b, Castle):
                b.hp = -1
        self._disconnected.discard(team)
        if not self._disconnected and not self._manually_paused:
            self._paused = False

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
            archer_r = archer._col_radius or 0.0
            tx, ty = tower.sprite_closest_point(archer.x, archer.y)
            if math.hypot(tx - archer.x, ty - archer.y) - archer_r <= TILE_SIZE * 0.5:
                if tower.garrison(archer):
                    self.game.units.remove(archer)
                done.append(archer_id)
            elif archer.attack_target is None:
                archer._navigate_to(tx, ty, self.game.nav_grid, archer_r + TILE_SIZE * 0.5)
        for archer_id in done:
            del self._pending_garrisons[archer_id]

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    def _apply_command(self, cmd: dict, player_team: str):
        kind = cmd.get("type")

        if kind == "CMD_MOVE":
            ids = set(cmd.get("unit_ids", []))
            _nav_scale = TILE_SIZE // NAV_TILE  # 4 nav cells per tile
            goal_nav_col = cmd.get("goal_col", 0) * _nav_scale
            goal_nav_row = cmd.get("goal_row", 0) * _nav_scale
            all_movable = self.game.units + self.game.pawns
            targets = [u for u in all_movable if u.entity_id in ids and u.team == player_team]
            offsets = self.game._formation_offsets(len(targets))
            for unit, (dc, dr) in zip(targets, offsets):
                dest = self.game.nav_grid.nearest_walkable(
                    goal_nav_col + dc * _nav_scale,
                    goal_nav_row + dr * _nav_scale,
                )
                start = (int(unit.x // NAV_TILE), int(unit.y // NAV_TILE))
                path = astar(self.game.nav_grid, start, dest)
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
                    archer_r = u._col_radius or 0.0
                    tx, ty = tower.sprite_closest_point(u.x, u.y)
                    if math.hypot(tx - u.x, ty - u.y) - archer_r <= TILE_SIZE * 0.5:
                        if tower.garrison(u):
                            self.game.units.remove(u)
                            self._pending_garrisons.pop(u.entity_id, None)
                    else:
                        u._navigate_to(tx, ty, self.game.nav_grid, archer_r + TILE_SIZE * 0.5)
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

        elif kind == "CMD_PAUSE":
            self._manually_paused = not self._manually_paused
            self._paused = self._manually_paused or bool(self._disconnected)

        elif kind == "CMD_SAVE":
            from datetime import datetime
            saves_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                     "savefiles")
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._save_pending = os.path.join(saves_dir, f"save_{ts}.json")
            self._paused = True

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
        self.game._enqueue_unit(unit_type, team=team, building=building)

    def _do_build(self, building_type: str, wx: float, wy: float, pawn_ids: set, team: str):
        from entities.blueprint import Blueprint, BUILDABLE
        from systems import collision
        cls_costs = BUILDABLE.get(building_type)
        if cls_costs is None:
            return
        cls, costs = cls_costs
        eco = self.game.economy[team]
        if not all(eco.get(k, 0) >= v for k, v in costs.items()):
            return
        building = cls(wx, wy, team=team)
        collision.register(building)
        if collision.any_overlap(building, self.game.collision_grid):
            return
        # Blueprints aren't in the collision grid (they're walkable so pawns
        # can reach them), so they need a separate placement-time check to
        # stop two builds piling on the same spot.
        if any(collision.overlaps(building, bp) for bp in self.game.blueprints):
            return
        for k, v in costs.items():
            eco[k] -= v
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
        survivors = [
            t for t in self.game.teams
            if any(b.team == t and isinstance(b, Castle) and b.alive
                   for b in self.game.buildings)
        ]
        if len(survivors) == 1 and len(self.game.teams) > 1:
            return survivors[0]
        return None
