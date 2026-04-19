import math
import pygame
from entities.entity import Entity
from map import TILE_SIZE


class Unit(Entity):
    """Intermediate base for all mobile units (combat and worker)."""

    MOVE_SPEED      = 96.0
    WAYPOINT_RADIUS = 4.0
    CHASE_INTERVAL  = 0.5
    DISPLAY_SIZE    = 96

    def __init__(self, x: float, y: float, team: str, max_hp: int = 100):
        super().__init__(x, y, team, max_hp)
        self.path: list[tuple[int, int]] = []
        self.attack_target = None
        self._time:           float = 0.0
        self._last_shot_time: float = 0.0
        self._chase_timer:    float = 0.0
        self._facing_right:   bool  = True

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def set_path(self, path: list[tuple[int, int]]):
        self.path = list(path)
        self.attack_target = None

    def set_attack_target(self, target):
        self.attack_target = target
        self.path = []

    # ------------------------------------------------------------------
    # Shared movement helpers
    # ------------------------------------------------------------------

    def _move_along_path(self, dt: float):
        if not self.path:
            return
        col, row = self.path[0]
        target_x = col * TILE_SIZE + TILE_SIZE / 2
        target_y = row * TILE_SIZE + TILE_SIZE / 2
        dx = target_x - self.x
        dy = target_y - self.y
        dist = math.hypot(dx, dy)
        if dist <= self.WAYPOINT_RADIUS:
            self.x, self.y = target_x, target_y
            self.path.pop(0)
            return
        speed = self.MOVE_SPEED * dt
        self.x += dx / dist * speed
        self.y += dy / dist * speed
        if abs(dx) > 1:
            self._facing_right = dx > 0

    def _dist_to_target(self) -> float:
        tx, ty = self.attack_target.closest_point(self.x, self.y)
        return math.hypot(tx - self.x, ty - self.y)

    def _repath_to_target(self, tile_map):
        from systems.pathfinding import astar
        sc = int(self.x // TILE_SIZE)
        sr = int(self.y // TILE_SIZE)
        tx, ty = self.attack_target.closest_point(self.x, self.y)
        gc = int(tx // TILE_SIZE)
        gr = int(ty // TILE_SIZE)
        gc, gr = tile_map.nearest_walkable(gc, gr)
        self.path = astar(tile_map, (sc, sr), (gc, gr))

    @property
    def sort_y(self) -> float:
        return self.y

    def hit_test(self, sx: float, sy: float, camera) -> bool:
        ux, uy = camera.world_to_screen(self.x, self.y)
        half = self.DISPLAY_SIZE * camera.zoom / 2
        return abs(sx - ux) <= half and abs(sy - uy) <= half
