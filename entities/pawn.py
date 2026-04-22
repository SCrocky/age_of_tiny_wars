import enum
import math
import rendering.entity_renderer as entity_renderer
from entities.unit import Unit
from map import TILE_SIZE

ANIM_FPS        = 8
GATHER_RATE     = 15    # resource units per second
CARRY_MAX       = 30
INTERACT_RADIUS = 60.0

# resource_type → (tool anim suffix, return anim suffix)
_RESOURCE_TOOL = {
    "wood": ("axe",     "wood"),
    "gold": ("pickaxe", "gold"),
    "meat": ("knife",   "meat"),
}

# Frame counts per anim key (from sprite sheet widths / 192px frame size)
_PAWN_FRAME_COUNTS: dict[str, int] = {
    "idle":             8,
    "run":              6,
    "run_axe":          6,
    "run_pickaxe":      6,
    "run_knife":        6,
    "interact_axe":     6,
    "interact_pickaxe": 6,
    "interact_knife":   4,
    "run_wood":         6,
    "run_gold":         6,
    "run_meat":         6,
    "run_hammer":       6,
    "interact_hammer":  3,
}


class Task(enum.Enum):
    IDLE        = "idle"
    TO_RESOURCE = "to_resource"
    GATHER      = "gather"
    TO_DEPOT    = "to_depot"
    TO_BUILD    = "to_build"
    BUILD       = "build"


def _nearest_walkable_south(col: int, row: int, tile_map) -> tuple[int, int]:
    """Nearest walkable tile, preferring south so pawns approach from the gate."""
    for r in range(1, 8):
        ring = [
            (dc, dr)
            for dc in range(-r, r + 1)
            for dr in range(-r, r + 1)
            if abs(dc) == r or abs(dr) == r
        ]
        ring.sort(key=lambda p: (p[0] != 0 and p[1] != 0, -p[1]))
        for dc, dr in ring:
            if tile_map.is_walkable(col + dc, row + dr):
                return col + dc, row + dr
    return col, row


class Pawn(Unit):
    """
    Worker unit.  Assign a gather task with assign_gather(resource_node, castle).
    The pawn will automatically cycle: travel → gather → return → deposit → repeat.

    Anim keys
    ---------
    Going to resource  : run_axe / run_pickaxe / run_knife
    Gathering          : interact_axe / interact_pickaxe / interact_knife
    Returning to depot : run_wood / run_gold / run_meat
    Building           : run_hammer / interact_hammer
    Idle / plain run   : idle / run
    """

    FRAME_SIZE      = 192
    DISPLAY_SIZE    = 80
    MOVE_SPEED      = 80.0
    DEPOSIT_RADIUS  = 60.0
    SELECT_RADIUS   = 18

    def __init__(self, x: float, y: float, team: str = "blue"):
        super().__init__(x, y, team, max_hp=50)

        self._task:          Task  = Task.IDLE
        self._anim_key:      str   = "idle"
        self._frame_idx:     int   = 0
        self._anim_timer:    float = 0.0

        # Gather task
        self._resource_node  = None
        self._buildings:     tuple = ()
        self._resource_type: str   = ""
        self._carried:       float = 0.0
        self._gather_timer:  float = 0.0

        # Build task
        self._blueprint = None

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def assign_build(self, blueprint):
        """Assign this pawn to construct a blueprint."""
        self._blueprint     = blueprint
        self._task          = Task.TO_BUILD
        self._resource_node = None
        self.path           = []

    def assign_gather(self, resource_node, buildings):
        """Assign this pawn to gather from resource_node and deposit at the nearest alive depot."""
        self._resource_node  = resource_node
        self._buildings      = tuple(buildings)
        self._resource_type  = resource_node.resource_type
        self._carried        = 0.0
        self._task           = Task.TO_RESOURCE
        self.path            = []

    # ------------------------------------------------------------------
    # Update  →  returns {'gold': n, 'wood': n, 'meat': n} deposit or {}
    # ------------------------------------------------------------------

    def update(self, dt: float, tile_map=None) -> dict:
        _dispatch = {
            Task.TO_RESOURCE: self._tick_to_resource,
            Task.GATHER:      self._tick_gather,
            Task.TO_DEPOT:    self._tick_to_depot,
            Task.TO_BUILD:    self._tick_to_build,
            Task.BUILD:       self._tick_build,
        }
        handler = _dispatch.get(self._task)
        if handler:
            deposit = handler(dt, tile_map)
        else:
            deposit = {}
            if self.path:
                self._move_along_path(dt)
        self._tick_animation(dt)
        return deposit

    # ------------------------------------------------------------------
    # Per-state tick methods
    # ------------------------------------------------------------------

    def _tick_to_resource(self, dt: float, tile_map) -> dict:
        if not self._resource_node or self._resource_node.depleted:
            self._task = Task.IDLE
        else:
            self._navigate_to(self._resource_node.x, self._resource_node.y,
                              dt, tile_map, arrive_radius=48.0)
            if math.hypot(self._resource_node.x - self.x,
                          self._resource_node.y - self.y) <= 48.0:
                self._task         = Task.GATHER
                self._gather_timer = 0.0
        return {}

    def _tick_gather(self, dt: float, tile_map) -> dict:
        self.path = []
        if not self._resource_node or self._resource_node.depleted:
            self._task = Task.TO_DEPOT if self._carried > 0 else Task.IDLE
        else:
            self._gather_timer += dt
            amount = max(1, int(GATHER_RATE * dt)) if self._gather_timer >= 1.0 / GATHER_RATE else 0
            gained = self._resource_node.gather(amount, gatherer=self)
            if gained:
                self._gather_timer = 0.0
                self._carried = min(CARRY_MAX, self._carried + gained)
            if self._carried >= CARRY_MAX:
                self._task = Task.TO_DEPOT
        return {}

    def _tick_to_depot(self, dt: float, tile_map) -> dict:
        depot = self._nearest_depot()
        if not depot:
            self._task = Task.IDLE
            return {}
        tx, ty = depot.closest_point(self.x, self.y)
        self._navigate_to(tx, ty, dt, tile_map, self.DEPOSIT_RADIUS)
        if math.hypot(tx - self.x, ty - self.y) <= self.DEPOSIT_RADIUS:
            carried = int(self._carried)
            deposit = {self._resource_type: carried} if carried > 0 else {}
            self._carried = 0.0
            self._task    = Task.TO_RESOURCE
            self.path     = []
            return deposit
        return {}

    def _tick_to_build(self, dt: float, tile_map) -> dict:
        if not self._blueprint or not self._blueprint.alive:
            self._task = Task.IDLE
        else:
            tx, ty = self._blueprint.closest_point(self.x, self.y)
            self._navigate_to(tx, ty, dt, tile_map, INTERACT_RADIUS)
            if math.hypot(tx - self.x, ty - self.y) <= INTERACT_RADIUS:
                self._task = Task.BUILD
        return {}

    def _tick_build(self, dt: float, tile_map) -> dict:
        self.path = []
        if not self._blueprint or not self._blueprint.alive:
            self._task = Task.IDLE
        else:
            dx = self._blueprint.x - self.x
            if abs(dx) > 1:
                self._facing_right = dx > 0
            from entities.blueprint import BUILD_RATE
            self._blueprint.add_progress(BUILD_RATE * dt)
        return {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _nearest_depot(self):
        depots = [b for b in self._buildings if b.alive and b.is_depot and b.team == self.team]
        if not depots:
            return None
        return min(depots, key=lambda d: math.hypot(d.x - self.x, d.y - self.y))

    def _navigate_to(self, tx: float, ty: float, dt: float, tile_map, arrive_radius: float):
        """Move toward (tx, ty); re-path if needed, direct-move when path exhausted."""
        if not self.path:
            if tile_map:
                sc = int(self.x // TILE_SIZE)
                sr = int(self.y // TILE_SIZE)
                if tile_map.is_walkable(sc, sr):
                    self._repath(tx, ty, tile_map)
        dist = math.hypot(tx - self.x, ty - self.y)
        if dist > arrive_radius:
            if self.path:
                self._move_along_path(dt)
            else:
                dx, dy = tx - self.x, ty - self.y
                step = self.MOVE_SPEED * dt
                self.x += dx / dist * step
                self.y += dy / dist * step
                if abs(dx) > 1:
                    self._facing_right = dx > 0

    def _repath(self, tx: float, ty: float, tile_map):
        from systems.pathfinding import astar
        sc = int(self.x // TILE_SIZE)
        sr = int(self.y // TILE_SIZE)
        gc = int(tx // TILE_SIZE)
        gr = int(ty // TILE_SIZE)
        if not tile_map.is_walkable(gc, gr):
            gc, gr = _nearest_walkable_south(gc, gr, tile_map)
        self.path = astar(tile_map, (sc, sr), (gc, gr))

    def _current_anim_key(self) -> str:
        if self._task is Task.TO_RESOURCE and self._resource_type:
            tool, _ = _RESOURCE_TOOL[self._resource_type]
            return f"run_{tool}"
        if self._task is Task.GATHER and self._resource_type:
            tool, _ = _RESOURCE_TOOL[self._resource_type]
            return f"interact_{tool}"
        if self._task is Task.TO_DEPOT and self._resource_type:
            _, ret = _RESOURCE_TOOL[self._resource_type]
            return f"run_{ret}"
        if self._task is Task.TO_BUILD: return "run_hammer"
        if self._task is Task.BUILD:    return "interact_hammer"
        if self.path:                   return "run"
        return "idle"

    def _tick_animation(self, dt: float):
        self._anim_key = self._current_anim_key()
        self._anim_timer += dt
        if self._anim_timer >= 1.0 / ANIM_FPS:
            self._anim_timer -= 1.0 / ANIM_FPS
            count = _PAWN_FRAME_COUNTS[self._anim_key]
            self._frame_idx = (self._frame_idx + 1) % count

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def render(self, surface, camera):
        entity_renderer.render_pawn(self, surface, camera)
