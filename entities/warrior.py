import rendering.entity_renderer as entity_renderer
from entities.combat_unit import CombatUnit

ATTACK_DAMAGE   = 25
ATTACK_COOLDOWN = 2.0
HIT_DELAY       = 0.5
GUARD_DURATION  = 0.5


class Warrior(CombatUnit):
    """
    Slow melee unit that guards against the first hit received during
    its attack cooldown, taking only half damage from that hit.
    """

    FRAME_SIZE    = 192
    DISPLAY_SIZE  = 128
    SELECT_RADIUS = 22
    MOVE_SPEED    = 80.0
    ATTACK_RANGE  = 55.0

    FRAME_COUNTS: dict[str, int] = {
        "idle":    8,
        "run":     6,
        "attack1": 4,
        "attack2": 4,
        "guard":   6,
    }

    def __init__(self, x: float, y: float, team: str = "blue"):
        super().__init__(x, y, team, max_hp=150)
        self._attack_set:  int   = 0
        self._guard_ready: bool  = True
        self._guard_timer: float = 0.0

    # ------------------------------------------------------------------
    # Damage interception
    # ------------------------------------------------------------------

    def receive_melee_hit(self, attacker):
        dx = attacker.x - self.x
        if abs(dx) > 1:
            self._facing_right = dx > 0

    def take_damage(self, amount: int, is_melee: bool = False):
        if is_melee and self._guard_ready:
            amount = max(1, amount // 2)
            self._guard_ready = False
            self._guard_timer = GUARD_DURATION
            self._frame_idx   = 0
        super().take_damage(amount)

    # ------------------------------------------------------------------
    # Update / attack
    # ------------------------------------------------------------------

    def update(self, dt: float, tile_map=None) -> list:
        self._guard_timer = max(0.0, self._guard_timer - dt)
        return super().update(dt, tile_map)

    def _tick_attack(self, dt: float):
        if self._time - self._last_shot_time < ATTACK_COOLDOWN:
            return None

        if self._action_timer == 0.0:
            self._frame_idx = 0

        dx = self.attack_target.x - self.x
        if abs(dx) > 1:
            self._facing_right = dx > 0

        self._action_timer += dt
        if self._action_timer >= HIT_DELAY:
            self.attack_target.take_damage(ATTACK_DAMAGE, is_melee=True)
            self.attack_target.receive_melee_hit(self)
            self._last_shot_time = self._time
            self._action_timer   = 0.0
            self._guard_ready    = True
            self._attack_set     = 1 - self._attack_set
            self._frame_idx      = 0
        return None

    def _current_anim_key(self) -> str:
        if self._guard_timer > 0:
            return "guard"
        if self._state == "attack":
            if self._time - self._last_shot_time < ATTACK_COOLDOWN:
                return "idle"
            return f"attack{self._attack_set + 1}"
        if self._state == "run":
            return "run"
        return "idle"

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def render(self, surface, camera):
        entity_renderer.render_warrior(self, surface, camera)
