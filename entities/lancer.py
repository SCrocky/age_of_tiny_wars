import math
import pygame
from entities.entity import Entity
from map import TILE_SIZE

MOVE_SPEED       = 88.0    # world px / second (slightly slower than archer)
ANIM_FPS         = 8
DISPLAY_SIZE     = 128     # render size in world px (frame is 320×320)
WAYPOINT_RADIUS  = 4.0

ATTACK_RANGE     = 50.0    # world px — melee range (~0.75 tiles)
ATTACK_DAMAGE    = 6       # 25 / 4 — one hit per animation cycle
ATTACK_COOLDOWN  = 0.3     # 1.2 / 4 — matches one animation cycle (~3 frames at 8fps)
HIT_DELAY        = 0.1     # seconds into cycle when damage lands
DEFENCE_DURATION = 0.5     # longer than ATTACK_COOLDOWN so hits keep it refreshed
CHASE_INTERVAL   = 0.5


# ---------------------------------------------------------------------------
# Direction helper
# ---------------------------------------------------------------------------

# The Lancer has 5 sprite directions; left-side directions are the right-side
# sprites flipped horizontally.
#
# Sector mapping (atan2 with y+ = screen-down):
#   0 = West      → Right, flip=True
#   1 = NW        → UpRight, flip=True
#   2 = North     → Up, flip=False
#   3 = NE        → UpRight, flip=False
#   4 = East      → Right, flip=False
#   5 = SE        → DownRight, flip=False
#   6 = South     → Down, flip=False
#   7 = SW        → DownRight, flip=True

_SECTOR_MAP = [
    ("Right",     True),
    ("UpRight",   True),
    ("Up",        False),
    ("UpRight",   False),
    ("Right",     False),
    ("DownRight", False),
    ("Down",      False),
    ("DownRight", True),
]


def _direction(dx: float, dy: float) -> tuple[str, bool]:
    """Return (sprite_key, flip_x) for a direction vector."""
    angle = math.degrees(math.atan2(dy, dx))          # -180 to 180
    sector = int((angle + 180 + 22.5) / 45) % 8
    return _SECTOR_MAP[sector]


def _load_sheet(path: str, frame_size: int) -> list[pygame.Surface]:
    sheet = pygame.image.load(path).convert_alpha()
    count = sheet.get_width() // frame_size
    return [
        sheet.subsurface(pygame.Rect(i * frame_size, 0, frame_size, frame_size))
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# Lancer class
# ---------------------------------------------------------------------------

class Lancer(Entity):
    """
    Melee unit with 8-directional attack animations.
    Automatically plays a directional defence animation when struck by melee.

    States (priority order)
    -----------------------
    defence – brief block animation triggered by receive_melee_hit()
    attack  – in melee range of target
    run     – following a path (move or chase)
    idle    – standing still
    """

    FRAME_SIZE = 320

    def __init__(self, x: float, y: float, team: str = "blue"):
        super().__init__(x, y, team, max_hp=120)

        folder = f"assets/Units/{team.capitalize()} Units/Lancer"
        fs = self.FRAME_SIZE

        # Directional attack / defence sheets keyed by direction name
        dirs = ("Right", "UpRight", "Up", "Down", "DownRight")
        self._frames_attack  = {d: _load_sheet(f"{folder}/Lancer_{d}_Attack.png",  fs) for d in dirs}
        self._frames_defence = {d: _load_sheet(f"{folder}/Lancer_{d}_Defence.png", fs) for d in dirs}
        self._frames_idle    = _load_sheet(f"{folder}/Lancer_Idle.png", fs)
        self._frames_run     = _load_sheet(f"{folder}/Lancer_Run.png",  fs)

        self._state:       str   = "idle"
        self._frame_idx:   int   = 0
        self._anim_timer:  float = 0.0
        self._facing_right: bool = True     # used for run/idle flipping

        # Directional state (attack / defence)
        self._dir_key:  str  = "Right"
        self._flip_dir: bool = False

        self.path: list[tuple[int, int]] = []

        # Combat
        self.attack_target           = None
        self.attack_range: float     = ATTACK_RANGE
        self._attack_cooldown: float = 0.0
        self._hit_timer:      float  = 0.0
        self._hit_dealt:      bool   = False
        self._chase_timer:    float  = 0.0

        # Defence
        self._defence_timer: float = 0.0
        self._def_dir_key:   str   = "Right"
        self._def_flip:      bool  = False

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def set_path(self, path: list[tuple[int, int]]):
        self.path = list(path)
        self.attack_target = None

    def set_attack_target(self, target):
        self.attack_target = target
        self.path = []

    def receive_melee_hit(self, attacker):
        """Trigger directional defence animation, but only if not currently attacking."""
        if self._state == "attack":
            return
        dx = attacker.x - self.x
        dy = attacker.y - self.y
        self._def_dir_key, self._def_flip = _direction(dx, dy)
        self._defence_timer = DEFENCE_DURATION
        self._frame_idx = 0   # restart defence animation

    # ------------------------------------------------------------------
    # Update  →  returns [] (no projectiles; deals damage directly)
    # ------------------------------------------------------------------

    def update(self, dt: float, tile_map=None) -> list:
        self._attack_cooldown = max(0.0, self._attack_cooldown - dt)

        # --- Defence takes priority over everything else ---
        if self._defence_timer > 0:
            self._defence_timer -= dt
            self._state = "defence"
            self._tick_animation(dt)
            return []

        # --- Combat / movement ---
        if self.attack_target is not None:
            if not self.attack_target.alive:
                self.attack_target = None
            else:
                dist = math.hypot(self.attack_target.x - self.x,
                                   self.attack_target.y - self.y)
                if dist <= self.attack_range:
                    self.path = []
                    self._state = "attack"
                    self._update_attack_direction()
                    self._tick_melee(dt)
                else:
                    self._state = "run"
                    self._hit_timer = 0.0
                    self._hit_dealt = False
                    if tile_map is not None:
                        self._chase_timer -= dt
                        if self._chase_timer <= 0:
                            self._chase_timer = CHASE_INTERVAL
                            self._repath_to_target(tile_map)
                    self._move_along_path(dt)

        elif self.path:
            self._state = "run"
            self._move_along_path(dt)
        else:
            self._state = "idle"

        self._tick_animation(dt)
        return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_attack_direction(self):
        dx = self.attack_target.x - self.x
        dy = self.attack_target.y - self.y
        self._dir_key, self._flip_dir = _direction(dx, dy)

    def _tick_melee(self, dt: float):
        if self._attack_cooldown > 0:
            return

        self._hit_timer += dt
        if not self._hit_dealt and self._hit_timer >= HIT_DELAY:
            self._hit_dealt = True
            self.attack_target.hp -= ATTACK_DAMAGE
            self.attack_target.receive_melee_hit(self)   # trigger defence anim
            self._attack_cooldown = ATTACK_COOLDOWN
            self._hit_timer       = 0.0
            self._hit_dealt       = False
            self._frame_idx       = 0

    def _repath_to_target(self, tile_map):
        from systems.pathfinding import astar
        sc = int(self.x // TILE_SIZE)
        sr = int(self.y // TILE_SIZE)
        gc = int(self.attack_target.x // TILE_SIZE)
        gr = int(self.attack_target.y // TILE_SIZE)
        self.path = astar(tile_map, (sc, sr), (gc, gr))

    def _move_along_path(self, dt: float):
        if not self.path:
            return
        col, row = self.path[0]
        tx = col * TILE_SIZE + TILE_SIZE / 2
        ty = row * TILE_SIZE + TILE_SIZE / 2
        dx, dy = tx - self.x, ty - self.y
        dist = math.hypot(dx, dy)
        if dist <= WAYPOINT_RADIUS:
            self.x, self.y = tx, ty
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
            length = self._current_frame_count()
            self._frame_idx = (self._frame_idx + 1) % length

    def _current_frame_count(self) -> int:
        if self._state == "attack":
            return len(self._frames_attack[self._dir_key])
        if self._state == "defence":
            return len(self._frames_defence[self._def_dir_key])
        if self._state == "run":
            return len(self._frames_run)
        return len(self._frames_idle)

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def render(self, surface: pygame.Surface, camera):
        frame, flip_x = self._get_frame()

        size   = max(1, int(DISPLAY_SIZE * camera.zoom))
        scaled = pygame.transform.scale(frame, (size, size))
        if flip_x:
            scaled = pygame.transform.flip(scaled, True, False)

        sx, sy = camera.world_to_screen(self.x, self.y)
        surface.blit(scaled, (int(sx - size / 2), int(sy - size / 2)))

        if self.selected:
            r = max(2, int(22 * camera.zoom))
            pygame.draw.circle(surface, (255, 220, 0), (int(sx), int(sy)), r, 2)

        self.draw_health_bar(surface, camera)

    def _get_frame(self) -> tuple[pygame.Surface, bool]:
        idx = self._frame_idx
        if self._state == "attack":
            frames = self._frames_attack[self._dir_key]
            return frames[idx % len(frames)], self._flip_dir
        if self._state == "defence":
            frames = self._frames_defence[self._def_dir_key]
            return frames[idx % len(frames)], self._def_flip
        if self._state == "run":
            frames = self._frames_run
            return frames[idx % len(frames)], not self._facing_right
        # idle
        frames = self._frames_idle
        return frames[idx % len(frames)], not self._facing_right

    # ------------------------------------------------------------------
    # Hit-test
    # ------------------------------------------------------------------

    def hit_test(self, sx: float, sy: float, camera) -> bool:
        ux, uy = camera.world_to_screen(self.x, self.y)
        half = DISPLAY_SIZE * camera.zoom / 2
        return abs(sx - ux) <= half and abs(sy - uy) <= half
