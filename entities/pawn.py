import math
import pygame
from entities.entity import Entity
from map import TILE_SIZE

MOVE_SPEED      = 80.0
ANIM_FPS        = 8
DISPLAY_SIZE    = 80    # world px (frame is 192×192)
WAYPOINT_RADIUS = 4.0
GATHER_RATE     = 15    # resource units per second
CARRY_MAX       = 30    # max resource units per trip
CHASE_INTERVAL  = 0.5


def _nearest_walkable(col: int, row: int, tile_map) -> tuple[int, int]:
    """Return the walkable tile nearest to (col, row).

    Cardinals (dc=0 or dr=0) are checked before diagonals so the result is as
    close as possible to the target in world-space.  South tiles are preferred
    over north so pawns approach the castle gate rather than the roof.
    """
    for r in range(1, 8):
        ring = [
            (dc, dr)
            for dc in range(-r, r + 1)
            for dr in range(-r, r + 1)
            if abs(dc) == r or abs(dr) == r
        ]
        # Cardinals first (closer in world-space), south before north
        ring.sort(key=lambda p: (p[0] != 0 and p[1] != 0, -p[1]))
        for dc, dr in ring:
            if tile_map.is_walkable(col + dc, row + dr):
                return col + dc, row + dr
    return col, row


def _load_sheet(path: str, frame_size: int = 192) -> list[pygame.Surface]:
    sheet = pygame.image.load(path).convert_alpha()
    count = sheet.get_width() // frame_size
    return [
        sheet.subsurface(pygame.Rect(i * frame_size, 0, frame_size, frame_size))
        for i in range(count)
    ]


class Pawn(Entity):
    """
    Worker unit.  Assign a gather task with assign_gather(resource_node, castle).
    The pawn will automatically cycle: travel → gather → return → deposit → repeat.

    Sprite selection
    ----------------
    Going to resource  : Run Axe / Pickaxe / Knife
    Gathering          : Interact Axe / Pickaxe / Knife
    Returning to castle: Run Wood / Gold / Meat
    Idle               : Idle
    """

    FRAME_SIZE = 192

    # Maps resource type → (tool_name, return_name)
    _RESOURCE_SPRITES = {
        "wood": ("Axe",      "Wood"),
        "gold": ("Pickaxe",  "Gold"),
        "meat": ("Knife",    "Meat"),
    }

    def __init__(self, x: float, y: float, team: str = "blue"):
        super().__init__(x, y, team, max_hp=50)

        folder = f"assets/Units/{team.capitalize()} Units/Pawn"
        fs = self.FRAME_SIZE

        self._frames_idle = _load_sheet(f"{folder}/Pawn_Idle.png", fs)
        self._frames_run  = _load_sheet(f"{folder}/Pawn_Run.png",  fs)

        # Lazy-loaded per resource type; populated in assign_gather
        self._frames_to:     list[pygame.Surface] = []
        self._frames_gather: list[pygame.Surface] = []
        self._frames_return: list[pygame.Surface] = []

        self._state:        str   = "idle"
        self._frame_idx:    int   = 0
        self._anim_timer:   float = 0.0
        self._facing_right: bool  = True

        self.path: list[tuple[int, int]] = []

        # Gather task
        self._resource_node  = None   # ResourceNode
        self._depots:        list = []  # buildings that accept resource deposits
        self._resource_type: str  = ""
        self._carried:       float = 0.0
        self._gather_timer:  float = 0.0
        self._task:          str   = ""    # 'to_resource' | 'gather' | 'to_depot'

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def assign_gather(self, resource_node, depots):
        """Assign this pawn to gather from resource_node and deposit at the nearest depot."""
        self._resource_node = resource_node
        self._depots        = depots if isinstance(depots, list) else [depots]
        self._resource_type = resource_node.resource_type

        folder = f"assets/Units/{self.team.capitalize()} Units/Pawn"
        fs = self.FRAME_SIZE
        tool, ret = self._RESOURCE_SPRITES[self._resource_type]
        self._frames_to     = _load_sheet(f"{folder}/Pawn_Run {tool}.png",      fs)
        self._frames_gather = _load_sheet(f"{folder}/Pawn_Interact {tool}.png", fs)
        self._frames_return = _load_sheet(f"{folder}/Pawn_Run {ret}.png",       fs)

        self._carried = 0.0
        self._task    = "to_resource"
        self.path     = []

    def set_path(self, path: list[tuple[int, int]]):
        """Send pawn to a position; any active gather task resumes afterward."""
        self.path = list(path)
        self.attack_target = None

    # Pawn is not a combatant
    attack_target = None

    # ------------------------------------------------------------------
    # Update  →  returns {'gold': n, 'wood': n, 'meat': n} deposit or {}
    # ------------------------------------------------------------------

    def update(self, dt: float, tile_map=None) -> dict:
        deposit = {}

        if self._task == "to_resource":
            self._state = "run_to"
            if not self._resource_node or self._resource_node.depleted:
                self._task = ""
                self._state = "idle"
            else:
                self._navigate_to(self._resource_node.x, self._resource_node.y,
                                  dt, tile_map, arrive_radius=48.0)
                dist = math.hypot(self._resource_node.x - self.x,
                                   self._resource_node.y - self.y)
                if dist <= 48.0:
                    self._task = "gather"
                    self._gather_timer = 0.0

        elif self._task == "gather":
            self._state = "gather"
            self.path   = []
            if not self._resource_node or self._resource_node.depleted:
                if self._carried > 0:
                    self._task = "to_depot"
                else:
                    self._task = ""
                    self._state = "idle"
            else:
                self._gather_timer += dt
                gained = self._resource_node.gather(int(GATHER_RATE * dt) or 1
                                                    if self._gather_timer >= 1.0 / GATHER_RATE
                                                    else 0)
                if gained:
                    self._gather_timer = 0.0
                    self._carried = min(CARRY_MAX, self._carried + gained)
                if self._carried >= CARRY_MAX:
                    self._task = "to_depot"

        elif self._task == "to_depot":
            self._state = "run_return"
            depot = self._nearest_depot()
            if depot:
                self._navigate_to(depot.x, depot.y,
                                  dt, tile_map, arrive_radius=depot.DEPOSIT_RADIUS)
                if depot.is_near(self.x, self.y):
                    carried = int(self._carried)
                    if carried > 0:
                        deposit = {self._resource_type: carried}
                    self._carried = 0.0
                    self._task    = "to_resource"
                    self.path     = []

        elif self.path:
            self._state = "run"
            self._move_along_path(dt)
        else:
            self._state = "idle"

        self._tick_animation(dt)
        return deposit

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _nearest_depot(self):
        if not self._depots:
            return None
        return min(self._depots, key=lambda d: math.hypot(d.x - self.x, d.y - self.y))

    def _navigate_to(self, tx: float, ty: float, dt: float, tile_map, arrive_radius: float):
        """Move toward (tx, ty); re-path if needed."""
        if not self.path:
            if tile_map:
                self._repath(tx, ty, tile_map)
        dist = math.hypot(tx - self.x, ty - self.y)
        if dist > arrive_radius:
            self._move_along_path(dt)

    def _repath(self, tx: float, ty: float, tile_map):
        from systems.pathfinding import astar
        sc = int(self.x // TILE_SIZE)
        sr = int(self.y // TILE_SIZE)
        gc = int(tx // TILE_SIZE)
        gr = int(ty // TILE_SIZE)
        if not tile_map.is_walkable(gc, gr):
            gc, gr = _nearest_walkable(gc, gr, tile_map)
        self.path = astar(tile_map, (sc, sr), (gc, gr))

    def _move_along_path(self, dt: float):
        if not self.path:
            return
        col, row = self.path[0]
        target_x = col * TILE_SIZE + TILE_SIZE / 2
        target_y = row * TILE_SIZE + TILE_SIZE / 2
        dx = target_x - self.x
        dy = target_y - self.y
        dist = math.hypot(dx, dy)
        if dist <= WAYPOINT_RADIUS:
            self.x, self.y = target_x, target_y
            self.path.pop(0)
            return
        speed = MOVE_SPEED * dt
        self.x += dx / dist * speed
        self.y += dy / dist * speed
        if abs(dx) > 1:
            self._facing_right = dx > 0

    def _tick_animation(self, dt: float):
        self._anim_timer += dt
        if self._anim_timer >= 1.0 / ANIM_FPS:
            self._anim_timer -= 1.0 / ANIM_FPS
            frames = self._current_frames()
            self._frame_idx = (self._frame_idx + 1) % len(frames)

    def _current_frames(self) -> list:
        if self._state == "run_to"     and self._frames_to:     return self._frames_to
        if self._state == "gather"     and self._frames_gather:  return self._frames_gather
        if self._state == "run_return" and self._frames_return:  return self._frames_return
        if self._state == "run":                                  return self._frames_run
        return self._frames_idle

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def render(self, surface: pygame.Surface, camera):
        frames = self._current_frames()
        frame  = frames[self._frame_idx % len(frames)]

        size   = max(1, int(DISPLAY_SIZE * camera.zoom))
        scaled = pygame.transform.scale(frame, (size, size))
        if not self._facing_right:
            scaled = pygame.transform.flip(scaled, True, False)

        sx, sy = camera.world_to_screen(self.x, self.y)
        surface.blit(scaled, (int(sx - size / 2), int(sy - size / 2)))

        if self.selected:
            r = max(2, int(18 * camera.zoom))
            pygame.draw.circle(surface, (255, 220, 0), (int(sx), int(sy)), r, 2)

        self.draw_health_bar(surface, camera)

        # Show carry amount when returning
        if self._task == "to_depot" and self._carried > 0:
            font = pygame.font.SysFont(None, max(12, int(16 * camera.zoom)))
            label = font.render(str(int(self._carried)), True, (255, 255, 180))
            surface.blit(label, (int(sx), int(sy - size / 2 - 14 * camera.zoom)))

    def hit_test(self, sx: float, sy: float, camera) -> bool:
        ux, uy = camera.world_to_screen(self.x, self.y)
        half = DISPLAY_SIZE * camera.zoom / 2
        return abs(sx - ux) <= half and abs(sy - uy) <= half
