import math
from entities.unit import Unit

ANIM_FPS       = 8
HEAL_RANGE     = 80.0
SEARCH_RADIUS  = 250.0
HEAL_AMOUNT    = 5
HEAL_COOLDOWN  = 1.0

FRAME_COUNTS: dict[str, int] = {"idle": 6, "run": 4, "heal": 11}


class Monk(Unit):
    DISPLAY_SIZE  = 128
    SELECT_RADIUS = 20

    def __init__(self, x: float, y: float, team: str = "blue"):
        super().__init__(x, y, team, max_hp=80)
        self._state:       str   = "idle"
        self._anim_key:    str   = "idle"
        self._frame_idx:   int   = 0
        self._anim_timer:  float = 0.0
        self._heal_timer:  float = 0.0
        self._ally_pool:   list  = []

    # attack_target is repurposed here as heal_target for movement/pathfinding reuse

    def update(self, dt: float, nav_grid=None, ally_pool=None) -> list:
        self._time += dt

        if ally_pool is not None:
            self._ally_pool = ally_pool

        # Drop target if it died or is fully healed
        if self.attack_target is not None:
            t = self.attack_target
            if not t.alive or t.hp >= t.max_hp:
                self.attack_target = None

        # Find a new target if idle
        if self.attack_target is None:
            self.attack_target = self.search_nearby_for(
                self._ally_pool,
                lambda e: e.alive and e.hp < e.max_hp,
                SEARCH_RADIUS,
            )

        if self.attack_target is not None:
            dist = math.hypot(self.attack_target.x - self.x,
                              self.attack_target.y - self.y)
            if dist <= HEAL_RANGE:
                self.path = []
                self._state = "heal"
                self._heal_timer += dt
                if self._heal_timer >= HEAL_COOLDOWN:
                    self._heal_timer -= HEAL_COOLDOWN
                    self.attack_target.hp = min(
                        self.attack_target.max_hp,
                        self.attack_target.hp + HEAL_AMOUNT,
                    )
            else:
                self._state = "run"
                self._chase(dt, nav_grid)
        elif self.path:
            self._state = "run"
            self._move_along_path(dt)
        else:
            self._state = "idle"

        self._tick_animation(dt)
        return []

    def _tick_animation(self, dt: float):
        self._anim_key    = self._state
        self._anim_timer += dt
        if self._anim_timer >= 1.0 / ANIM_FPS:
            self._anim_timer -= 1.0 / ANIM_FPS
            count            = FRAME_COUNTS[self._anim_key]
            self._frame_idx  = (self._frame_idx + 1) % count

