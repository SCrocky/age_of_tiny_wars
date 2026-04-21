import math
from entities.entity import Entity

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
