import math
import pygame
from entities.unit import Unit
from map import TILE_SIZE

ANIM_FPS        = 8
ATTACK_DAMAGE   = 6
ATTACK_COOLDOWN = 0.3
HIT_DELAY       = 0.1
DEFENCE_DURATION = 0.5


def _load_sheet(path: str, frame_size: int) -> list[pygame.Surface]:
    sheet = pygame.image.load(path).convert_alpha()
    count = sheet.get_width() // frame_size
    return [
        sheet.subsurface(pygame.Rect(i * frame_size, 0, frame_size, frame_size))
        for i in range(count)
    ]


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
    angle = math.degrees(math.atan2(dy, dx))
    sector = int((angle + 180 + 22.5) / 45) % 8
    return _SECTOR_MAP[sector]


# ---------------------------------------------------------------------------


class Lancer(Unit):
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

    FRAME_SIZE   = 320
    DISPLAY_SIZE = 128
    MOVE_SPEED   = 88.0
    ATTACK_RANGE = 50.0

    def __init__(self, x: float, y: float, team: str = "blue"):
        super().__init__(x, y, team, max_hp=120)

        folder = f"assets/Units/{team.capitalize()} Units/Lancer"
        fs = self.FRAME_SIZE

        dirs = ("Right", "UpRight", "Up", "Down", "DownRight")
        self._frames_attack  = {d: _load_sheet(f"{folder}/Lancer_{d}_Attack.png",  fs) for d in dirs}
        self._frames_defence = {d: _load_sheet(f"{folder}/Lancer_{d}_Defence.png", fs) for d in dirs}
        self._frames_idle    = _load_sheet(f"{folder}/Lancer_Idle.png", fs)
        self._frames_run     = _load_sheet(f"{folder}/Lancer_Run.png",  fs)

        self._state:       str   = "idle"
        self._frame_idx:   int   = 0
        self._anim_timer:  float = 0.0

        self._dir_key:  str  = "Right"
        self._flip_dir: bool = False

        self.attack_range: float = self.ATTACK_RANGE
        self._hit_timer:   float = 0.0

        self._defence_timer: float = 0.0
        self._def_dir_key:   str   = "Right"
        self._def_flip:      bool  = False

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def receive_melee_hit(self, attacker):
        """Trigger directional defence animation, but only if not currently attacking."""
        if self._state == "attack":
            return
        dx = attacker.x - self.x
        dy = attacker.y - self.y
        self._def_dir_key, self._def_flip = _direction(dx, dy)
        self._defence_timer = DEFENCE_DURATION
        self._frame_idx = 0

    # ------------------------------------------------------------------
    # Update  →  returns [] (no projectiles; deals damage directly)
    # ------------------------------------------------------------------

    def update(self, dt: float, tile_map=None) -> list:
        self._time += dt

        if self._defence_timer > 0:
            self._defence_timer -= dt
            self._state = "defence"
            self._tick_animation(dt)
            return []

        if self.attack_target is not None:
            if not self.attack_target.alive:
                self.attack_target = None
            else:
                if self._dist_to_target() <= self.attack_range:
                    self.path = []
                    self._state = "attack"
                    self._update_attack_direction()
                    self._tick_melee(dt)
                else:
                    self._state     = "run"
                    self._hit_timer = 0.0
                    if tile_map is not None:
                        self._chase_timer -= dt
                        if self._chase_timer <= 0:
                            self._chase_timer = self.CHASE_INTERVAL
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
        if self._time - self._last_shot_time < ATTACK_COOLDOWN:
            return

        if self._hit_timer == 0.0:
            self._frame_idx = 0

        self._hit_timer += dt
        if self._hit_timer >= HIT_DELAY:
            self.attack_target.take_damage(ATTACK_DAMAGE, is_melee=True)
            self.attack_target.receive_melee_hit(self)
            self._last_shot_time = self._time
            self._hit_timer      = 0.0
            self._frame_idx      = 0

    def _tick_animation(self, dt: float):
        self._anim_timer += dt
        if self._anim_timer >= 1.0 / ANIM_FPS:
            self._anim_timer -= 1.0 / ANIM_FPS
            length = self._current_frame_count()
            if self._state == "attack" and self._frame_idx >= length - 1:
                pass  # hold last frame until next swing resets to 0
            else:
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

        size   = max(1, int(self.DISPLAY_SIZE * camera.zoom))
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
        frames = self._frames_idle
        return frames[idx % len(frames)], not self._facing_right
