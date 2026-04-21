import rendering.entity_renderer as entity_renderer
from entities.unit import Unit
from entities.projectile import Arrow, ARROW_DAMAGE

ANIM_FPS = 8

_ARCHER_FRAME_COUNTS: dict[str, int] = {
    "idle":   6,
    "run":    4,
    "attack": 8,
}


class Archer(Unit):
    """Ranged combat unit."""

    VISION_RADIUS = 7

    FRAME_SIZE      = 192
    DISPLAY_SIZE    = 96
    SELECT_RADIUS   = 20
    ATTACK_RANGE    = 200.0
    ATTACK_COOLDOWN = 1.5
    SHOOT_DELAY     = 0.4

    def __init__(self, x: float, y: float, team: str = "blue"):
        super().__init__(x, y, team, max_hp=80)

        self._state:       str   = "idle"
        self._anim_key:    str   = "idle"
        self._frame_idx:   int   = 0
        self._anim_timer:  float = 0.0

        self.attack_range: float = self.ATTACK_RANGE
        self._shoot_timer: float = 0.0

    # ------------------------------------------------------------------
    # Update  →  returns list of Arrow objects to be added to the world
    # ------------------------------------------------------------------

    def update(self, dt: float, tile_map=None) -> list[Arrow]:
        spawned: list[Arrow] = []

        self._time += dt

        if self.attack_target is not None:
            if not self.attack_target.alive:
                self.attack_target = None
            else:
                if self._dist_to_target() <= self.attack_range:
                    self.path = []
                    self._state = "attack"
                    arrow = self._tick_attack(dt)
                    if arrow:
                        spawned.append(arrow)
                else:
                    self._state       = "run"
                    self._shoot_timer = 0.0
                    self._chase(dt, tile_map)

        elif self.path:
            self._state = "run"
            self._move_along_path(dt)
        else:
            self._state = "idle"

        self._tick_animation(dt)
        return spawned

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _tick_attack(self, dt: float):
        if self._time - self._last_shot_time < self.ATTACK_COOLDOWN:
            return None

        tx, _ = self.attack_target.closest_point(self.x, self.y)
        dx = tx - self.x
        if abs(dx) > 1:
            self._facing_right = dx > 0

        if self._shoot_timer == 0.0:
            self._frame_idx = 0

        self._shoot_timer += dt

        if self._shoot_timer >= self.SHOOT_DELAY:
            self._last_shot_time = self._time
            self._shoot_timer    = 0.0
            return Arrow(self.x, self.y, self.attack_target, ARROW_DAMAGE, self.team)

        return None

    def _tick_animation(self, dt: float):
        self._anim_key    = self._state
        self._anim_timer += dt
        if self._anim_timer >= 1.0 / ANIM_FPS:
            self._anim_timer -= 1.0 / ANIM_FPS
            count = _ARCHER_FRAME_COUNTS[self._anim_key]
            if self._state == "attack" and self._frame_idx >= count - 1:
                pass  # hold last frame until next shot resets to 0
            else:
                self._frame_idx = (self._frame_idx + 1) % count

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def render(self, surface, camera):
        entity_renderer.render_archer(self, surface, camera)
