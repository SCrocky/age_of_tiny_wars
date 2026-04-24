import json
import math
import random
from map import TileMap, TILE_SIZE
from entities.archer import Archer
from entities.lancer import Lancer
from entities.warrior import Warrior
from entities.pawn import Pawn
from entities.building import Building, Castle, Archery, Barracks, House, Tower
from entities.resource import GoldNode, WoodNode, MeatNode
from entities.projectile import Arrow
from entities.blueprint import Blueprint

_BUILDING_CLS = {
    "Castle":   Castle,
    "Archery":  Archery,
    "Barracks": Barracks,
    "House":    House,
    "Tower":    Tower,
}
_UNIT_CLS = {
    "Archer":  Archer,
    "Lancer":  Lancer,
    "Warrior": Warrior,
}


class Game:
    def __init__(self, scene_path: str):
        self.units:      list            = []
        self.pawns:      list[Pawn]      = []
        self.arrows:     list[Arrow]     = []
        self.buildings:  list[Building]  = []
        self.blueprints: list[Blueprint] = []
        self.resources:  list            = []

        self.economy: dict[str, dict[str, int]] = {
            "blue":  {"gold": 60, "wood": 600, "meat": 60, "pop": 0, "pop_cap": 0},
            "black": {"gold": 60, "wood": 60, "meat": 60, "pop": 0, "pop_cap": 0},
        }

        self._next_entity_id: int = 1
        self._load_scene(scene_path)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _assign_id(self, entity):
        entity.entity_id = self._next_entity_id
        self._next_entity_id += 1
        return entity

    def _load_scene(self, path: str):
        with open(path) as f:
            scene = json.load(f)

        self.map = TileMap.from_data(scene["cols"], scene["rows"], scene["tiles"])

        for b_data in scene.get("buildings", []):
            cls = _BUILDING_CLS.get(b_data["type"])
            if cls is None:
                continue
            kw = {}
            if b_data["type"] == "House":
                kw["variant"] = b_data.get("variant", 1)
            building = self._assign_id(cls(b_data["x"], b_data["y"], team=b_data["team"], **kw))
            self.map.clear_area(building.x, building.y, tile_radius=4)
            building.on_place(self.map)
            self.buildings.append(building)

        for u_data in scene.get("units", []):
            x, y, team = u_data["x"], u_data["y"], u_data["team"]
            if u_data["type"] == "Pawn":
                self.pawns.append(self._assign_id(Pawn(x, y, team=team)))
            else:
                cls = _UNIT_CLS.get(u_data["type"])
                if cls:
                    self.units.append(self._assign_id(cls(x, y, team=team)))

        for r_data in scene.get("resources", []):
            x, y, variant = r_data["x"], r_data["y"], r_data.get("variant", 0)
            rtype = r_data["type"]
            if rtype == "wood":
                self.resources.append(self._assign_id(WoodNode(x, y, variant=variant)))
            elif rtype == "gold":
                self.resources.append(self._assign_id(GoldNode(x, y, variant=variant)))
            elif rtype == "meat":
                self.resources.append(self._assign_id(MeatNode(x, y)))

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def _recalc_pop(self):
        for team in ("blue", "black"):
            eco = self.economy[team]
            eco["pop"] = sum(1 for u in self.units + self.pawns if u.team == team)
            eco["pop_cap"] = sum(
                b.pop_bonus
                for b in self.buildings
                if b.team == team and b.alive and b.pop_bonus > 0
            )

    def update(self, dt: float):
        for unit in self.units:
            new_arrows = unit.update(dt, self.map)
            for arrow in new_arrows:
                self._assign_id(arrow)
            self.arrows.extend(new_arrows)

        for building in self.buildings:
            if isinstance(building, Tower) and building.garrisoned_archer is not None:
                enemies = [e for e in self.units + self.pawns + self.buildings
                           if e.team != building.team and getattr(e, "alive", True)]
                new_arrows = building.update_garrison(dt, enemies, self.map)
                for arrow in new_arrows:
                    self._assign_id(arrow)
                self.arrows.extend(new_arrows)

        for pawn in self.pawns:
            deposit = pawn.update(dt, self.map)
            for resource_type, amount in deposit.items():
                self.economy[pawn.team][resource_type] += amount

        for arrow in self.arrows:
            arrow.update(dt)

        for res in self.resources:
            res.update(dt)

        self._apply_separation(dt)
        self._apply_building_collision()

        next_buildings  = []
        next_blueprints = []
        for bp in self.blueprints:
            if bp.alive and bp.progress >= bp.max_hp:
                building = self._assign_id(bp.complete())
                building.on_place(self.map)
                next_buildings.append(building)
            elif bp.alive:
                next_blueprints.append(bp)
        for b in self.buildings:
            if b.alive:
                next_buildings.append(b)
            else:
                b.on_destroy(self.map)
        self.buildings  = next_buildings
        self.blueprints = next_blueprints

        self.units  = [u for u in self.units  if u.alive]
        self.pawns  = [p for p in self.pawns  if p.alive]
        self.arrows = [a for a in self.arrows if a.alive]
        self._recalc_pop()

    def _apply_building_collision(self):
        for unit in self.units + self.pawns:
            r = unit.DISPLAY_SIZE / 4
            for building in self.buildings + self.blueprints:
                hw = building.COLLISION_W / 2 + r
                hh = building.COLLISION_H / 2 + r
                dx = unit.x - building.x
                dy = unit.y - building.y
                ox = hw - abs(dx)
                oy = hh - abs(dy)
                if ox > 0 and oy > 0:
                    if ox <= oy:
                        unit.x += ox * (1 if dx >= 0 else -1)
                    else:
                        unit.y += oy * (1 if dy >= 0 else -1)

    def _apply_separation(self, dt: float):
        RADIUS = 52.0
        FORCE  = 180.0
        all_units = self.units + self.pawns
        for i, a in enumerate(all_units):
            fx = fy = 0.0
            for j, b in enumerate(all_units):
                if i == j:
                    continue
                dx = a.x - b.x
                dy = a.y - b.y
                dist = math.hypot(dx, dy)
                if 0 < dist < RADIUS:
                    strength = (RADIUS - dist) / RADIUS
                    fx += dx / dist * strength
                    fy += dy / dist * strength
            new_x = a.x + fx * FORCE * dt
            new_y = a.y + fy * FORCE * dt
            if self.map.is_walkable(int(new_x // TILE_SIZE), int(a.y // TILE_SIZE)):
                a.x = new_x
            if self.map.is_walkable(int(a.x // TILE_SIZE), int(new_y // TILE_SIZE)):
                a.y = new_y

    # ------------------------------------------------------------------
    # Server-facing helpers
    # ------------------------------------------------------------------

    _SPAWN_TABLE = {
        "Pawn":    (Pawn,    {"meat": 20},             None),
        "Archer":  (Archer,  {"wood": 15, "meat": 30}, Archery),
        "Lancer":  (Lancer,  {"wood": 45, "meat": 10}, Barracks),
        "Warrior": (Warrior, {"gold": 35, "meat": 40}, Barracks),
    }

    def _spawn_unit(self, unit_type: str, team: str = "blue", building=None):
        unit_cls, costs, building_cls = self._SPAWN_TABLE[unit_type]
        eco = self.economy[team]
        if eco["pop"] >= eco["pop_cap"]:
            return
        if any(eco.get(r, 0) < amt for r, amt in costs.items()):
            return
        spawn_building = building or next(
            (b for b in self.buildings
             if b.team == team and b.selected and b.alive
             and (building_cls is None or isinstance(b, building_cls))),
            None,
        )
        if spawn_building is None:
            return
        for r, amt in costs.items():
            eco[r] -= amt
        angle = random.uniform(0, 2 * math.pi)
        unit = self._assign_id(unit_cls(
            spawn_building.x + math.cos(angle) * 120,
            spawn_building.y + math.sin(angle) * 120,
            team=team,
        ))
        (self.pawns if unit_cls is Pawn else self.units).append(unit)

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
