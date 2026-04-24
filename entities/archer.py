from entities.combat_unit import CombatUnit
from entities.projectile import Arrow, ARROW_DAMAGE


class Archer(CombatUnit):
    """Ranged combat unit."""

    VISION_RADIUS = 7

    DISPLAY_SIZE    = 96
    SELECT_RADIUS   = 20
    ATTACK_RANGE    = 200.0
    ATTACK_COOLDOWN = 1.5
    SHOOT_DELAY     = 0.4

    FRAME_COUNTS: dict[str, int] = {
        "idle":   6,
        "run":    4,
        "attack": 8,
    }

    def __init__(self, x: float, y: float, team: str = "blue"):
        super().__init__(x, y, team, max_hp=80)

    def _tick_attack(self, dt: float):
        if self._time - self._last_shot_time < self.ATTACK_COOLDOWN:
            return None

        tx, _ = self.attack_target.closest_point(self.x, self.y)
        dx = tx - self.x
        if abs(dx) > 1:
            self._facing_right = dx > 0

        if self._action_timer == 0.0:
            self._frame_idx = 0

        self._action_timer += dt

        if self._action_timer >= self.SHOOT_DELAY:
            self._last_shot_time = self._time
            self._action_timer   = 0.0
            return Arrow(self.x, self.y, self.attack_target, ARROW_DAMAGE, self.team)

        return None
