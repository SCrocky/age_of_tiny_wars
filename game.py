import json
import math
import random
from datetime import datetime, timezone, timedelta
from map import TileMap, NavGrid, NAV_TILE, TILE_SIZE
from entities.archer import Archer
from entities.lancer import Lancer
from entities.warrior import Warrior
from entities.monk import Monk
from entities.pawn import Pawn, Task as PawnTask
from entities.building import Building, ProductionBuilding, Castle, Archery, Barracks, House, Tower, Monastery

_UTC = timezone.utc
from entities.resource import GoldNode, WoodNode, MeatNode
from entities.projectile import Arrow
from entities.blueprint import Blueprint
from entities.teams import teams_from_scene
from systems import collision
from logging_config import get_logger

log = get_logger("game")

_BUILDING_CLS = {
    "Castle":    Castle,
    "Archery":   Archery,
    "Barracks":  Barracks,
    "House":     House,
    "Tower":     Tower,
    "Monastery": Monastery,
}
_UNIT_CLS = {
    "Archer":  Archer,
    "Lancer":  Lancer,
    "Warrior": Warrior,
    "Monk":    Monk,
}


class Game:
    def __init__(self, scene_path: str):
        self.units:      list            = []
        self.pawns:      list[Pawn]      = []
        self.arrows:     list[Arrow]     = []
        self.buildings:  list[Building]  = []
        self.blueprints: list[Blueprint] = []
        self.resources:  list            = []

        self.teams: list[str] = []
        self.economy: dict[str, dict[str, int]] = {}

        self._next_entity_id: int = 1
        collision.init()
        self.collision_grid = collision.StaticGrid()
        self._load_scene(scene_path)
        # Populate the static grid once everything has been loaded.
        # Blueprints are intentionally NOT added — under-construction sites are
        # walkable so pawns (and everyone else) can reach the build target.
        # Placement validation still excludes blueprint overlaps; see
        # network/server._do_build.
        for b in self.buildings: self.collision_grid.add(b)
        for r in self.resources:
            # MeatNode (sheep) is dynamic — it moves; everything else is static.
            if not isinstance(r, MeatNode):
                self.collision_grid.add(r)
                r._in_grid = True

        # Fine-grained 16-px navigation grid: water blocked at init,
        # buildings and static resources registered as obstacles.
        self.nav_grid = NavGrid(self.map)
        for b in self.buildings:
            self.nav_grid.block_rect(*b.nav_footprint)
        for r in self.resources:
            if not isinstance(r, MeatNode) and not r.depleted:
                self.nav_grid.block_rect(*r.nav_footprint)

        self.last_tick_time: datetime = datetime.now(_UTC)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _assign_id(self, entity):
        entity.entity_id = self._next_entity_id
        self._next_entity_id += 1
        collision.register(entity)
        return entity

    def save(self, path: str) -> None:
        """Serialize current game state to a JSON save file."""
        import json, os
        from datetime import datetime, timezone
        from entities.building import House, Tower

        buildings_out = []
        for b in self.buildings:
            if not b.alive:
                continue
            entry = {"id": b.entity_id, "type": type(b).__name__, "x": b.x, "y": b.y,
                     "team": b.team, "hp": b.hp}
            if isinstance(b, House):
                entry["variant"] = int(b.sprite_key.split("/")[1][-1])
            if isinstance(b, Tower) and b.garrisoned_archer is not None:
                entry["garrisoned_archer"] = {"hp": b.garrisoned_archer.hp}
            if isinstance(b, ProductionBuilding) and b.production_queue:
                entry["production_queue"] = list(b.production_queue)
                entry["production_end"] = b.production_end.isoformat() if b.production_end else None
            buildings_out.append(entry)

        blueprints_out = []
        for bp in self.blueprints:
            if not bp.alive:
                continue
            b = bp._building
            entry = {"id": bp.entity_id, "type": type(b).__name__, "x": b.x, "y": b.y,
                     "team": b.team, "progress": bp.progress}
            if isinstance(b, House):
                entry["variant"] = int(b.sprite_key.split("/")[1][-1])
            blueprints_out.append(entry)

        units_out = []
        for u in self.units:
            if not u.alive:
                continue
            entry = {"id": u.entity_id, "type": type(u).__name__, "x": u.x, "y": u.y,
                     "team": u.team, "hp": u.hp}
            if u.attack_target is not None and getattr(u.attack_target, "alive", False):
                entry["attack_target_id"] = u.attack_target.entity_id
            units_out.append(entry)
        for p in self.pawns:
            if not p.alive:
                continue
            entry = {"id": p.entity_id, "type": "Pawn", "x": p.x, "y": p.y,
                     "team": p.team, "hp": p.hp,
                     "task": p._task.value,
                     "resource_type": p._resource_type,
                     "carried": p._carried}
            if p._resource_node is not None:
                entry["resource_node_id"] = p._resource_node.entity_id
            if p._blueprint is not None:
                entry["blueprint_id"] = p._blueprint.entity_id
            units_out.append(entry)

        resources_out = []
        for r in self.resources:
            entry = {"id": r.entity_id, "type": r.resource_type, "x": r.x, "y": r.y,
                     "amount": r.amount}
            if hasattr(r, "sprite_key"):
                n = int(r.sprite_key.split("/")[2])
                # Invert constructor formulas to recover original variant arg:
                #   WoodNode: n = (variant % 4) + 1  →  variant = n - 1
                #   GoldNode: n = max(1, min(6, variant))  →  variant = n
                entry["variant"] = n - 1 if r.resource_type == "wood" else n
            else:
                entry["variant"] = 0
            resources_out.append(entry)

        teams = list(self.economy.keys())
        data = {
            "save_version":  1,
            "timestamp":     datetime.now(_UTC).isoformat(),
            "last_tick_time": self.last_tick_time.isoformat(),
            "rows":         self.map.rows,
            "cols":         self.map.cols,
            "tile_px":      TILE_SIZE,
            "tileset":      "Tilemap_color1",
            "tiles":        self.map.tiles,
            # Stub spawns so teams_from_scene() and server seat-validation keep working.
            "spawns":       [{"team": t, "x": 0.0, "y": 0.0} for t in teams],
            "economy":      {t: dict(eco) for t, eco in self.economy.items()},
            "buildings":    buildings_out,
            "blueprints":   blueprints_out,
            "units":        units_out,
            "resources":    resources_out,
        }

        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, separators=(",", ":"))
        log.info("saved → %s", path)

    def _load_scene(self, path: str):
        with open(path) as f:
            scene = json.load(f)

        self.map = TileMap.from_data(scene["cols"], scene["rows"], scene["tiles"])

        self.teams = teams_from_scene(scene)
        self.economy = {
            t: {"gold": 60, "wood": 60, "meat": 60, "pop": 0, "pop_cap": 0}
            for t in self.teams
        }
        if "economy" in scene:
            for team, saved in scene["economy"].items():
                if team in self.economy:
                    for k in ("gold", "wood", "meat"):
                        if k in saved:
                            self.economy[team][k] = saved[k]

        # Maps saved entity_id → newly created entity for cross-reference resolution.
        _saved_id_map: dict[int, object] = {}

        for b_data in scene.get("buildings", []):
            cls = _BUILDING_CLS.get(b_data["type"])
            if cls is None:
                continue
            kw = {}
            if b_data["type"] == "House":
                kw["variant"] = b_data.get("variant", 1)
            building = self._assign_id(cls(b_data["x"], b_data["y"], team=b_data["team"], **kw))
            self.map.clear_area(building.x, building.y, tile_radius=4)
            if "hp" in b_data:
                building.hp = b_data["hp"]
            if isinstance(building, Tower) and "garrisoned_archer" in b_data:
                archer_data = b_data["garrisoned_archer"]
                archer = self._assign_id(Archer(building.x, building.y, team=building.team))
                archer.hp = archer_data.get("hp", archer.max_hp)
                building.garrison(archer)
            if isinstance(building, ProductionBuilding) and b_data.get("production_queue"):
                for ut in b_data["production_queue"]:
                    building.production_queue.append(ut)
                pe = b_data.get("production_end")
                if pe:
                    building.production_end = datetime.fromisoformat(pe)
            if "id" in b_data:
                _saved_id_map[b_data["id"]] = building
            self.buildings.append(building)

        if "last_tick_time" in scene:
            saved_ltt = datetime.fromisoformat(scene["last_tick_time"])
            shift = datetime.now(_UTC) - saved_ltt
            self.shift_all_production(shift)

        for bp_data in scene.get("blueprints", []):
            cls = _BUILDING_CLS.get(bp_data["type"])
            if cls is None:
                continue
            kw = {}
            if bp_data["type"] == "House":
                kw["variant"] = bp_data.get("variant", 1)
            b = cls(bp_data["x"], bp_data["y"], team=bp_data["team"], **kw)
            self.map.clear_area(b.x, b.y, tile_radius=4)
            bp = self._assign_id(Blueprint(b))
            bp.progress = float(bp_data.get("progress", 0.0))
            if "id" in bp_data:
                _saved_id_map[bp_data["id"]] = bp
            self.blueprints.append(bp)

        # Collect (entity, data) pairs for cross-reference resolution after all entities loaded.
        _unit_data_pairs: list[tuple] = []
        _pawn_data_pairs: list[tuple] = []

        for u_data in scene.get("units", []):
            x, y, team = u_data["x"], u_data["y"], u_data["team"]
            if u_data["type"] == "Pawn":
                p = self._assign_id(Pawn(x, y, team=team))
                if "hp" in u_data:
                    p.hp = u_data["hp"]
                if "id" in u_data:
                    _saved_id_map[u_data["id"]] = p
                _pawn_data_pairs.append((p, u_data))
                self.pawns.append(p)
            else:
                cls = _UNIT_CLS.get(u_data["type"])
                if cls:
                    u = self._assign_id(cls(x, y, team=team))
                    if "hp" in u_data:
                        u.hp = u_data["hp"]
                    if "id" in u_data:
                        _saved_id_map[u_data["id"]] = u
                    _unit_data_pairs.append((u, u_data))
                    self.units.append(u)

        for r_data in scene.get("resources", []):
            x, y, variant = r_data["x"], r_data["y"], r_data.get("variant", 0)
            rtype = r_data["type"]
            if rtype == "wood":
                node = self._assign_id(WoodNode(x, y, variant=variant))
            elif rtype == "gold":
                node = self._assign_id(GoldNode(x, y, variant=variant))
            elif rtype == "meat":
                node = self._assign_id(MeatNode(x, y))
            else:
                continue
            if "amount" in r_data:
                node.amount = r_data["amount"]
            if "id" in r_data:
                _saved_id_map[r_data["id"]] = node
            self.resources.append(node)

        # --- Second pass: resolve cross-references ---

        _valid_task_values = {t.value for t in PawnTask}

        for p, p_data in _pawn_data_pairs:
            task_str = p_data.get("task", "idle")
            task = PawnTask(task_str) if task_str in _valid_task_values else PawnTask.IDLE
            p._task          = task
            p._resource_type = p_data.get("resource_type", "")
            p._carried       = float(p_data.get("carried", 0.0))
            p._buildings     = tuple(self.buildings)

            if task in (PawnTask.TO_RESOURCE, PawnTask.GATHER, PawnTask.TO_DEPOT):
                p._resource_pool = self.resources
                node = _saved_id_map.get(p_data.get("resource_node_id"))
                if node is not None and not node.depleted:
                    p._resource_node = node
                elif task != PawnTask.TO_DEPOT:
                    # No valid node; pawn will idle (TO_DEPOT can proceed without a node)
                    p._task = PawnTask.IDLE

            if task in (PawnTask.TO_BUILD, PawnTask.BUILD):
                p._blueprint_pool = self.blueprints
                bp = _saved_id_map.get(p_data.get("blueprint_id"))
                if bp is not None and bp.alive:
                    p._blueprint = bp
                else:
                    p._task = PawnTask.IDLE

        for u, u_data in _unit_data_pairs:
            target_id = u_data.get("attack_target_id")
            if target_id is not None:
                target = _saved_id_map.get(target_id)
                if target is not None and getattr(target, "alive", False):
                    u.attack_target = target

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def _recalc_pop(self):
        for team in self.teams:
            eco = self.economy[team]
            eco["pop"] = sum(1 for u in self.units + self.pawns if u.team == team)
            eco["pop_cap"] = sum(
                b.pop_bonus
                for b in self.buildings
                if b.team == team and b.alive and b.pop_bonus > 0
            )

    def update(self, dt: float):
        _now = datetime.now(_UTC)
        _combatants = [e for e in self.units + self.pawns + self.buildings if getattr(e, "alive", True)]
        _enemy_pool: dict[str, list] = {}
        _ally_pool:  dict[str, list] = {}
        for unit in self.units:
            if unit.team not in _enemy_pool:
                _enemy_pool[unit.team] = [e for e in _combatants if e.team != unit.team]
            if unit.team not in _ally_pool:
                _ally_pool[unit.team] = [u for u in self.units + self.pawns if u.team == unit.team]

        # Dynamic entities (move each tick) — small list, scanned linearly.
        # Statics (buildings, blueprints, trees, gold) live in self.collision_grid.
        grid = self.collision_grid
        sheep = [r for r in self.resources if isinstance(r, MeatNode) and not r.depleted]
        dynamics = [u for u in self.units if u.alive] \
                 + [p for p in self.pawns if p.alive] \
                 + sheep

        for unit in self.units:
            old_x, old_y = unit.x, unit.y
            if isinstance(unit, Monk):
                unit.update(dt, self.nav_grid, _ally_pool.get(unit.team, []))
            else:
                new_arrows = unit.update(dt, self.nav_grid, _enemy_pool.get(unit.team, []))
                for arrow in new_arrows:
                    self._assign_id(arrow)
                self.arrows.extend(new_arrows)
            if unit.x != old_x or unit.y != old_y:
                collision.resolve_move(unit, old_x, old_y, grid, dynamics)

        for building in self.buildings:
            if isinstance(building, Tower) and building.garrisoned_archer is not None:
                enemies = [e for e in self.units + self.pawns + self.buildings
                           if e.team != building.team and getattr(e, "alive", True)]
                new_arrows = building.update_garrison(dt, enemies, self.nav_grid)
                for arrow in new_arrows:
                    self._assign_id(arrow)
                self.arrows.extend(new_arrows)
            if isinstance(building, ProductionBuilding):
                self._tick_production(building, _now)

        for pawn in self.pawns:
            old_x, old_y = pawn.x, pawn.y
            deposit = pawn.update(dt, self.nav_grid)
            for resource_type, amount in deposit.items():
                self.economy[pawn.team][resource_type] += amount
            if pawn.x != old_x or pawn.y != old_y:
                skip_wood = pawn._task is PawnTask.GATHER
                collision.resolve_move(pawn, old_x, old_y, grid, dynamics, skip_wood)

        # Prune depleted static resources from the collision grid so the hot
        # loop never has to filter them. Pawns may have just depleted a node
        # via their _tick_gather call above.
        for res in self.resources:
            if getattr(res, "_in_grid", False) and res.depleted:
                grid.remove(res)
                res._in_grid = False
                self.nav_grid.unblock_rect(*res.nav_footprint)

        for arrow in self.arrows:
            arrow.update(dt)

        for res in self.resources:
            if isinstance(res, MeatNode):
                if res.depleted:
                    continue
                old_x, old_y = res.x, res.y
                res.update(dt)
                if res.x != old_x or res.y != old_y:
                    collision.resolve_move(res, old_x, old_y, grid, dynamics)
            else:
                res.update(dt)

        # Resolve residual unit-vs-unit overlaps after all positions are settled.
        collision.separate_units(dynamics)

        next_buildings  = []
        next_blueprints = []
        for bp in self.blueprints:
            if bp.alive and bp.progress >= bp.max_hp:
                building = self._assign_id(bp.complete())
                # Blueprint was never in the grid; only register the new
                # building so it now physically blocks movement.
                grid.add(building)
                self.nav_grid.block_rect(*building.nav_footprint)
                next_buildings.append(building)
            elif bp.alive:
                next_blueprints.append(bp)
        for b in self.buildings:
            if b.alive:
                next_buildings.append(b)
            else:
                grid.remove(b)
                self.nav_grid.unblock_rect(*b.nav_footprint)
                if isinstance(b, Tower) and b.garrisoned_archer is not None:
                    b.garrisoned_archer.alive = False
                    b.garrisoned_archer = None
        self.buildings  = next_buildings
        self.blueprints = next_blueprints

        self.units  = [u for u in self.units  if u.alive]
        self.pawns  = [p for p in self.pawns  if p.alive]
        self.arrows = [a for a in self.arrows if a.alive]
        self.last_tick_time = _now
        self._recalc_pop()

    # ------------------------------------------------------------------
    # Server-facing helpers
    # ------------------------------------------------------------------

    _SPAWN_TABLE = {
        "Pawn":    (Pawn,    {"meat": 20},             None),
        "Archer":  (Archer,  {"wood": 15, "meat": 30}, Archery),
        "Lancer":  (Lancer,  {"wood": 45, "meat": 10}, Barracks),
        "Warrior": (Warrior, {"gold": 35, "meat": 40}, Barracks),
        "Monk":    (Monk,    {"gold": 20, "meat": 30}, Monastery),
    }

    def _spiral_spawn(self, building) -> tuple[float, float] | None:
        angle = random.uniform(0, 2 * math.pi)
        half_w = building.DISPLAY_W / 2
        half_h = building.DISPLAY_H / 2
        min_r = math.hypot(half_w, half_h) + NAV_TILE
        for radius in range(int(min_r), int(min_r) + 200, NAV_TILE):
            for step in range(0, 360, 15):
                a = angle + math.radians(step)
                cx = building.x + math.cos(a) * radius
                cy = building.y + math.sin(a) * radius
                if self.nav_grid.is_walkable(int(cx // NAV_TILE), int(cy // NAV_TILE)):
                    return cx, cy
        return None

    def _enqueue_unit(self, unit_type: str, team: str, building) -> bool:
        if unit_type not in self._SPAWN_TABLE:
            return False
        _, costs, building_cls = self._SPAWN_TABLE[unit_type]
        if not isinstance(building, ProductionBuilding):
            return False
        if building_cls is not None and not isinstance(building, building_cls):
            return False
        eco = self.economy[team]
        if any(eco.get(r, 0) < amt for r, amt in costs.items()):
            return False
        if not building.enqueue(unit_type):
            return False
        for r, amt in costs.items():
            eco[r] -= amt
        return True

    def _tick_production(self, building: ProductionBuilding, now: datetime):
        if not building.production_queue or building.production_end is None:
            return
        if now < building.production_end:
            return
        unit_type = building.production_queue[0]
        eco = self.economy[building.team]
        if eco["pop"] >= eco["pop_cap"]:
            building.production_end = now  # mark ready; retry each tick
            return
        pos = self._spiral_spawn(building)
        if pos is None:
            building.production_end = now  # retry
            return
        building.production_queue.popleft()
        unit_cls = self._SPAWN_TABLE[unit_type][0]
        unit = self._assign_id(unit_cls(*pos, team=building.team))
        (self.pawns if unit_cls is Pawn else self.units).append(unit)
        if building.production_queue:
            building.production_end = datetime.now(_UTC) + timedelta(seconds=building.PRODUCTION_TIME)
        else:
            building.production_end = None

    def shift_all_production(self, delta: timedelta):
        for b in self.buildings:
            if isinstance(b, ProductionBuilding):
                b.shift_end(delta)

    @staticmethod
    def _formation_offsets(count: int) -> list[tuple[int, int]]:
        offsets = [(0, 0)]
        ring = 1
        while len(offsets) < count:
            for dc in range(-ring, ring + 1):
                for dr in range(-ring, ring + 1):
                    if max(abs(dc), abs(dr)) == ring:
                        offsets.append((dc, dr))
                        if len(offsets) == count:
                            return offsets
            ring += 1
        return offsets[:count]
