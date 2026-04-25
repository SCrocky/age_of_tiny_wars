import math
import random
from entities.entity import Entity
from map import TILE_SIZE


class Unit(Entity):
    """Intermediate base for all mobile units (combat and worker)."""

    MOVE_SPEED      = 96.0
    WAYPOINT_RADIUS = 4.0
    CHASE_INTERVAL  = 0.5
    DISPLAY_SIZE    = 96
    SELECT_RADIUS   = 20

    def __init__(self, x: float, y: float, team: str, max_hp: int = 100):
        super().__init__(x, y, team, max_hp)
        self.path: list[tuple[int, int]] = []
        self.attack_target = None
        self._enemy_pool:  list = []
        self._time:           float = 0.0
        self._last_shot_time: float = 0.0
        self._chase_timer:    float = 0.0
        self._facing_right:   bool  = True
        self._arrival_offset: tuple[float, float] = (0.0, 0.0)
        self._path_future = None   # pending async A* result

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def set_path(self, path: list[tuple[int, int]]):
        self._path_future = None   # discard any pending repath
        self.path = list(path)
        self.attack_target = None
        if path:
            self._arrival_offset = (random.uniform(-12.0, 12.0), random.uniform(-12.0, 12.0))
        else:
            self._arrival_offset = (0.0, 0.0)

    def set_attack_target(self, target, enemy_pool=None):
        self._path_future  = None
        self.attack_target = target
        self._enemy_pool   = enemy_pool if enemy_pool is not None else []
        self.path          = []

    # ------------------------------------------------------------------
    # Shared movement helpers
    # ------------------------------------------------------------------

    def _move_along_path(self, dt: float):
        if not self.path:
            return
        col, row = self.path[0]
        target_x = col * TILE_SIZE + TILE_SIZE / 2
        target_y = row * TILE_SIZE + TILE_SIZE / 2
        if len(self.path) == 1:
            target_x += self._arrival_offset[0]
            target_y += self._arrival_offset[1]
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

    def _chase(self, dt: float, tile_map):
        """Follow path toward attack_target; step directly if path is exhausted."""
        if tile_map is not None:
            self._chase_timer -= dt
            if self._chase_timer <= 0:
                self._chase_timer = self.CHASE_INTERVAL
                self._repath_to_target(tile_map)

        # Apply completed async path result
        if self._path_future is not None and self._path_future.done():
            try:
                result = self._path_future.result()
                if result:
                    self.path = result
            except Exception:
                pass
            self._path_future = None

        if self.path:
            self._move_along_path(dt)
        elif self.attack_target:
            tx, ty = self.attack_target.closest_point(self.x, self.y)
            dx, dy = tx - self.x, ty - self.y
            dist = math.hypot(dx, dy)
            if dist > 0:
                step = self.MOVE_SPEED * dt
                self.x += dx / dist * step
                self.y += dy / dist * step
                if abs(dx) > 1:
                    self._facing_right = dx > 0

    def _repath_to_target(self, tile_map):
        from systems.pathfinding import submit_astar
        sc = int(self.x // TILE_SIZE)
        sr = int(self.y // TILE_SIZE)
        get_point = getattr(self.attack_target, 'sprite_closest_point', self.attack_target.closest_point)
        tx, ty = get_point(self.x, self.y)
        gc = int(tx // TILE_SIZE)
        gr = int(ty // TILE_SIZE)
        gc, gr = tile_map.nearest_walkable(gc, gr)
        self._path_future = submit_astar(tile_map, (sc, sr), (gc, gr))

    @property
    def sort_y(self) -> float:
        return self.y

    def search_nearby_for(self, candidates, predicate, radius: float):
        """Return the nearest candidate within radius satisfying predicate, or None."""
        best, best_dist = None, radius
        for obj in candidates:
            d = math.hypot(obj.x - self.x, obj.y - self.y)
            if d < best_dist and predicate(obj):
                best, best_dist = obj, d
        return best

    def hit_test(self, sx: float, sy: float, camera) -> bool:
        ux, uy = camera.world_to_screen(self.x, self.y)
        half = self.DISPLAY_SIZE * camera.zoom / 2
        return abs(sx - ux) <= half and abs(sy - uy) <= half

    # ------------------------------------------------------------------
