import math
import random
from entities.entity import Entity
from map import NAV_TILE


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
        # (tx, ty, arrive_radius) set by _navigate_to; consumed once per update tick.
        self._approach_target: tuple[float, float, float] | None = None

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def set_path(self, path: list[tuple[int, int]]):
        self._path_future = None   # discard any pending repath
        self.path = list(path)
        self.attack_target = None
        self._approach_target = None
        if path:
            self._arrival_offset = (random.uniform(-12.0, 12.0), random.uniform(-12.0, 12.0))
        else:
            self._arrival_offset = (0.0, 0.0)

    def set_attack_target(self, target, enemy_pool=None):
        self._path_future  = None
        self.attack_target = target
        self._enemy_pool   = enemy_pool if enemy_pool is not None else []
        self.path          = []
        self._approach_target = None

    # ------------------------------------------------------------------
    # Shared movement helpers
    # ------------------------------------------------------------------

    def _move_along_path(self, dt: float):
        if not self.path:
            return
        col, row = self.path[0]
        target_x = col * NAV_TILE + NAV_TILE / 2
        target_y = row * NAV_TILE + NAV_TILE / 2
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

    def _chase(self, dt: float, nav_grid):
        """Follow path toward attack_target; step directly if path is exhausted."""
        if nav_grid is not None:
            self._chase_timer -= dt
            if self._chase_timer <= 0:
                self._chase_timer = self.CHASE_INTERVAL
                self._repath_to_target(nav_grid)

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

    def _repath_to_target(self, nav_grid):
        from systems.pathfinding import submit_astar
        sc = int(self.x // NAV_TILE)
        sr = int(self.y // NAV_TILE)
        get_point = getattr(self.attack_target, 'sprite_closest_point', self.attack_target.closest_point)
        tx, ty = get_point(self.x, self.y)
        gc = int(tx // NAV_TILE)
        gr = int(ty // NAV_TILE)
        gc, gr = nav_grid.nearest_walkable(gc, gr)
        self._path_future = submit_astar(nav_grid, (sc, sr), (gc, gr))

    def _navigate_to(self, tx: float, ty: float, nav_grid, arrive_radius: float):
        """Plan an approach toward (tx, ty); the unit's update tick performs the movement."""
        self._approach_target = (tx, ty, arrive_radius)
        if not self.path and nav_grid:
            sc = int(self.x // NAV_TILE)
            sr = int(self.y // NAV_TILE)
            if nav_grid.is_walkable(sc, sr):
                self._repath(tx, ty, nav_grid)

    def _repath(self, tx: float, ty: float, nav_grid):
        from systems.pathfinding import astar
        sc = int(self.x // NAV_TILE)
        sr = int(self.y // NAV_TILE)
        gc = int(tx // NAV_TILE)
        gr = int(ty // NAV_TILE)
        if not nav_grid.is_walkable(gc, gr):
            gc, gr = nav_grid.nearest_walkable(gc, gr)
        self.path = astar(nav_grid, (sc, sr), (gc, gr))

    def _step_approach(self, dt: float):
        """Move one tick toward the stored approach target; clears the target on use."""
        if self._approach_target is None:
            return
        tx, ty, radius = self._approach_target
        self._approach_target = None
        dist = math.hypot(tx - self.x, ty - self.y)
        if dist <= radius:
            return
        if self.path:
            self._move_along_path(dt)
        else:
            dx, dy = tx - self.x, ty - self.y
            step = self.MOVE_SPEED * dt
            self.x += dx / dist * step
            self.y += dy / dist * step
            if abs(dx) > 1:
                self._facing_right = dx > 0

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
