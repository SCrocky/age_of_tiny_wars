import math
from entities.entity import Entity
from entities.projectile import ARROW_DAMAGE, ARROW_SPEED

TILE_SIZE = 64


class Building(Entity):
    """Base class for all static structures."""

    DISPLAY_W        = 64
    DISPLAY_H        = 64
    COLLISION_W      = DISPLAY_W
    COLLISION_H      = DISPLAY_H
    is_depot         = False
    pop_bonus        = 0
    HEALTH_BAR_WIDTH = 60

    def __init__(self, x: float, y: float, team: str, max_hp: int = 200):
        super().__init__(x, y, team, max_hp)

    def closest_point(self, x: float, y: float) -> tuple[float, float]:
        hw = self.COLLISION_W / 2
        hh = self.COLLISION_H / 2
        return (
            max(self.x - hw, min(x, self.x + hw)),
            max(self.y - hh, min(y, self.y + hh)),
        )

    def sprite_closest_point(self, x: float, y: float) -> tuple[float, float]:
        hw = self.DISPLAY_W / 2
        hh = self.DISPLAY_H / 2
        return (
            max(self.x - hw, min(x, self.x + hw)),
            max(self.y - hh, min(y, self.y + hh)),
        )

    def _tile_half(self) -> tuple[int, int]:
        hw = math.ceil(self.COLLISION_W / 2 / TILE_SIZE)
        hh = math.ceil(self.COLLISION_H / 2 / TILE_SIZE)
        return hw, hh

    def on_place(self, tile_map):
        tile_map.block_area(self.x, self.y, *self._tile_half())

    def on_destroy(self, tile_map):
        tile_map.unblock_area(self.x, self.y, *self._tile_half())

    def hit_test(self, sx: float, sy: float, camera) -> bool:
        ux, uy = camera.world_to_screen(self.x, self.y)
        hw = self.DISPLAY_W * camera.zoom / 2
        hh = self.DISPLAY_H * camera.zoom / 2
        return abs(sx - ux) <= hw and abs(sy - uy) <= hh


# ---------------------------------------------------------------------------


class Archery(Building):
    DISPLAY_W   = 192
    DISPLAY_H   = 192
    COLLISION_W = 140
    COLLISION_H = 100

    def __init__(self, x: float, y: float, team: str):
        super().__init__(x, y, team, max_hp=300)
        self.sprite_key = f"building/archery/{team}"


class Barracks(Building):
    DISPLAY_W   = 192
    DISPLAY_H   = 192
    COLLISION_W = 140
    COLLISION_H = 100

    def __init__(self, x: float, y: float, team: str):
        super().__init__(x, y, team, max_hp=350)
        self.sprite_key = f"building/barracks/{team}"


class House(Building):
    DISPLAY_W        = 128
    DISPLAY_H        = 128
    COLLISION_W      = 90
    COLLISION_H      = 70
    is_depot         = True
    pop_bonus        = 5
    HEALTH_BAR_WIDTH = 50

    def __init__(self, x: float, y: float, team: str, variant: int = 1):
        super().__init__(x, y, team, max_hp=150)
        n = max(1, min(3, variant))
        self.sprite_key = f"building/house{n}/{team}"


_GARRISONED_RANGE    = 450.0          # ~2.25× normal attack range
_GARRISONED_COOLDOWN = 0.7            # ~2× faster than normal 1.5 s
_GARRISONED_DAMAGE   = ARROW_DAMAGE * 2
_GARRISONED_SPEED    = ARROW_SPEED   * 2


class Tower(Building):
    DISPLAY_W        = 128
    DISPLAY_H        = 256
    COLLISION_W      = 80
    COLLISION_H      = 80
    VISION_RADIUS    = 10
    HEALTH_BAR_WIDTH = 50

    def __init__(self, x: float, y: float, team: str):
        super().__init__(x, y, team, max_hp=300)
        self.sprite_key = f"building/tower/{team}"
        self.garrisoned_archer = None

    def garrison(self, archer) -> bool:
        if self.garrisoned_archer is not None:
            return False
        self.garrisoned_archer = archer
        archer._orig_attack_range   = archer.attack_range
        archer._orig_attack_cooldown = archer.ATTACK_COOLDOWN
        archer.attack_range      = _GARRISONED_RANGE
        archer.ATTACK_COOLDOWN   = _GARRISONED_COOLDOWN  # instance attr overrides class
        archer.x = self.x
        archer.y = self.y
        archer.path = []
        archer.attack_target = None
        return True

    def release_archer(self):
        archer = self.garrisoned_archer
        if archer is None:
            return None
        self.garrisoned_archer = None
        archer.attack_range    = archer._orig_attack_range
        archer.ATTACK_COOLDOWN = archer._orig_attack_cooldown
        del archer._orig_attack_range
        del archer._orig_attack_cooldown
        archer.x = self.x
        archer.y = self.y + self.COLLISION_H / 2 + 30
        archer.path = []
        archer.attack_target = None
        return archer

    def update_garrison(self, dt: float, enemies: list, tile_map) -> list:
        """Tick the garrisoned archer's attack logic; return any new Arrow objects."""
        archer = self.garrisoned_archer
        if archer is None:
            return []

        if archer.attack_target is None or not archer.attack_target.alive:
            best, best_dist = None, _GARRISONED_RANGE
            for e in enemies:
                if not e.alive:
                    continue
                d = math.hypot(e.x - self.x, e.y - self.y)
                if d < best_dist:
                    best, best_dist = e, d
            archer.attack_target = best
            if best:
                archer._enemy_pool = enemies

        arrows = archer.update(dt, tile_map)

        # Lock position so the archer can never leave the tower
        archer.x = self.x
        archer.y = self.y
        archer.path = []

        for arrow in arrows:
            arrow.damage  = _GARRISONED_DAMAGE
            arrow._speed  = _GARRISONED_SPEED

        return arrows

    def on_destroy(self, tile_map):
        super().on_destroy(tile_map)
        if self.garrisoned_archer is not None:
            self.garrisoned_archer.alive = False
            self.garrisoned_archer = None


class Castle(Building):
    DISPLAY_W        = 320
    DISPLAY_H        = 256
    COLLISION_W      = 220
    COLLISION_H      = 100
    is_depot         = True
    pop_bonus        = 10
    HEALTH_BAR_WIDTH = 80
    VISION_RADIUS    = 8

    def __init__(self, x: float, y: float, team: str):
        super().__init__(x, y, team, max_hp=500)
        self.sprite_key = f"building/castle/{team}"
