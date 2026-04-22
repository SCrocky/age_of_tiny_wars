import math
import rendering.entity_renderer as entity_renderer
from entities.combat_unit import CombatUnit

ATTACK_DAMAGE    = 6
ATTACK_COOLDOWN  = 0.3
HIT_DELAY        = 0.1
DEFENCE_DURATION = 0.5

# ---------------------------------------------------------------------------
# Direction helper — pure math, no pygame
# ---------------------------------------------------------------------------

# Sector mapping (atan2 with y+ = screen-down):
#   0 = West   → Right,     flip=True
#   1 = NW     → UpRight,   flip=True
#   2 = North  → Up,        flip=False
#   3 = NE     → UpRight,   flip=False
#   4 = East   → Right,     flip=False
#   5 = SE     → DownRight, flip=False
#   6 = South  → Down,      flip=False
#   7 = SW     → DownRight, flip=True

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
    """Return (dir_key, flip_x) for a direction vector."""
    angle  = math.degrees(math.atan2(dy, dx))
    sector = int((angle + 180 + 22.5) / 45) % 8
    return _SECTOR_MAP[sector]


# ---------------------------------------------------------------------------


class Lancer(CombatUnit):
    """
    Melee unit with 8-directional attack animations.
    Automatically plays a directional defence animation when struck by melee.
    """

    FRAME_SIZE    = 320
    DISPLAY_SIZE  = 128
    SELECT_RADIUS = 22
    MOVE_SPEED    = 88.0
    ATTACK_RANGE  = 50.0

    FRAME_COUNTS: dict[str, int] = {
        "attack":  3,
        "defence": 6,
        "idle":    12,
        "run":     6,
    }

    def __init__(self, x: float, y: float, team: str = "blue"):
        super().__init__(x, y, team, max_hp=120)
        self._dir_key:       str   = "Right"
        self._flip_dir:      bool  = False
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
        self._frame_idx     = 0

    # ------------------------------------------------------------------
    # CombatUnit hooks
    # ------------------------------------------------------------------

    def _pre_state_tick(self, dt: float):
        if self._defence_timer > 0:
            self._defence_timer -= dt
            self._state = "defence"
            self._tick_animation(dt)
            return []
        return None

    def _on_enter_attack(self):
        dx = self.attack_target.x - self.x
        dy = self.attack_target.y - self.y
        self._dir_key, self._flip_dir = _direction(dx, dy)

    def _tick_attack(self, dt: float):
        if self._time - self._last_shot_time < ATTACK_COOLDOWN:
            return None

        if self._action_timer == 0.0:
            self._frame_idx = 0

        self._action_timer += dt
        if self._action_timer >= HIT_DELAY:
            self.attack_target.take_damage(ATTACK_DAMAGE, is_melee=True)
            self.attack_target.receive_melee_hit(self)
            self._last_shot_time = self._time
            self._action_timer   = 0.0
            self._frame_idx      = 0
        return None

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def render(self, surface, camera):
        entity_renderer.render_lancer(self, surface, camera)
