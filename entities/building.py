import math
from entities.entity import Entity
from entities.projectile import ARROW_DAMAGE, ARROW_SPEED


class Building(Entity):
    """Base class for all static structures."""

    DISPLAY_W        = 64
    DISPLAY_H        = 64
    is_depot         = False
    pop_bonus        = 0
    HEALTH_BAR_WIDTH = 60

    def __init__(self, x: float, y: float, team: str, max_hp: int = 200):
        super().__init__(x, y, team, max_hp)

    def sprite_closest_point(self, x: float, y: float) -> tuple[float, float]:
        hw = self.DISPLAY_W / 2
        hh = self.DISPLAY_H / 2
        return (
            max(self.x - hw, min(x, self.x + hw)),
            max(self.y - hh, min(y, self.y + hh)),
        )

    def hit_test(self, sx: float, sy: float, camera) -> bool:
        ux, uy = camera.world_to_screen(self.x, self.y)
        hw = self.DISPLAY_W * camera.zoom / 2
        hh = self.DISPLAY_H * camera.zoom / 2
        return abs(sx - ux) <= hw and abs(sy - uy) <= hh

    @property
    def nav_footprint(self) -> tuple[float, float, float, float]:
        """World-pixel (left, top, width, height) used to block the nav grid."""
        return (self.x - self.DISPLAY_W / 2, self.y - self.DISPLAY_H / 2,
                self.DISPLAY_W, self.DISPLAY_H)


# ---------------------------------------------------------------------------


class Archery(Building):
    DISPLAY_W = 192
    DISPLAY_H = 256

    def __init__(self, x: float, y: float, team: str):
        super().__init__(x, y, team, max_hp=300)
        self.sprite_key = f"building/archery/{team}"


class Barracks(Building):
    DISPLAY_W = 192
    DISPLAY_H = 256

    def __init__(self, x: float, y: float, team: str):
        super().__init__(x, y, team, max_hp=350)
        self.sprite_key = f"building/barracks/{team}"


class House(Building):
    DISPLAY_W        = 128
    DISPLAY_H        = 128
    is_depot         = True
    pop_bonus        = 5
    HEALTH_BAR_WIDTH = 50

    def __init__(self, x: float, y: float, team: str, variant: int = 1):
        super().__init__(x, y, team, max_hp=150)
        n = max(1, min(3, variant))
        self.sprite_key = f"building/house{n}/{team}"


class Monastery(Building):
    DISPLAY_W = 192
    DISPLAY_H = 320

    def __init__(self, x: float, y: float, team: str):
        super().__init__(x, y, team, max_hp=300)
        self.sprite_key = f"building/monastery/{team}"


_GARRISONED_RANGE    = 450.0          # ~2.25× normal attack range
_GARRISONED_COOLDOWN = 0.7            # ~2× faster than normal 1.5 s
_GARRISONED_DAMAGE   = ARROW_DAMAGE * 2
_GARRISONED_SPEED    = ARROW_SPEED   * 2


class Tower(Building):
    DISPLAY_W        = 128
    DISPLAY_H        = 256
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
        archer.y = self.y + 70
        archer.path = []
        archer.attack_target = None
        return archer

    def update_garrison(self, dt: float, enemies: list, nav_grid) -> list:
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

        arrows = archer.update(dt, nav_grid)

        # Lock position so the archer can never leave the tower
        archer.x = self.x
        archer.y = self.y
        archer.path = []

        for arrow in arrows:
            arrow.damage  = _GARRISONED_DAMAGE
            arrow._speed  = _GARRISONED_SPEED

        return arrows


class Castle(Building):
    DISPLAY_W        = 320
    DISPLAY_H        = 256
    is_depot         = True
    pop_bonus        = 10
    HEALTH_BAR_WIDTH = 80
    VISION_RADIUS    = 8

    def __init__(self, x: float, y: float, team: str):
        super().__init__(x, y, team, max_hp=500)
        self.sprite_key = f"building/castle/{team}"
