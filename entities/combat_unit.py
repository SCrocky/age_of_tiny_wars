from entities.unit import Unit

ANIM_FPS            = 8
NEARBY_ENEMY_RADIUS = 320.0  # 5 tiles — auto-retarget range on kill


class CombatUnit(Unit):
    """Shared base for Archer, Warrior, and Lancer.

    Subclasses must define:
      ATTACK_RANGE : float  — class constant
      FRAME_COUNTS : dict[str, int]  — anim key → frame count

    Subclasses should override:
      _tick_attack(dt)     — perform attack logic; return a projectile or None
      _pre_state_tick(dt)  — return a list to short-circuit update(), None to proceed
      _on_enter_attack()   — called each frame the unit is within attack range
      _current_anim_key()  — map _state → anim key string (default: identity)
    """

    ATTACK_RANGE: float         = 0.0
    FRAME_COUNTS: dict[str, int] = {}

    def __init__(self, x: float, y: float, team: str, max_hp: int):
        super().__init__(x, y, team, max_hp)
        self._state:        str   = "idle"
        self._anim_key:     str   = "idle"
        self._frame_idx:    int   = 0
        self._anim_timer:   float = 0.0
        self.attack_range:  float = self.ATTACK_RANGE
        self._action_timer: float = 0.0

    # ------------------------------------------------------------------
    # Main update loop
    # ------------------------------------------------------------------

    def update(self, dt: float, tile_map=None) -> list:
        self._time += dt

        early = self._pre_state_tick(dt)
        if early is not None:
            return early

        spawned = []
        if self.attack_target is not None:
            if not self.attack_target.alive:
                self.attack_target = self.search_nearby_for(
                    self._enemy_pool,
                    lambda e: e.alive and e.team != self.team,
                    NEARBY_ENEMY_RADIUS,
                )
            else:
                if self._dist_to_target() <= self.attack_range:
                    self.path = []
                    self._state = "attack"
                    self._on_enter_attack()
                    result = self._tick_attack(dt)
                    if result is not None:
                        spawned.append(result)
                else:
                    self._state        = "run"
                    self._action_timer = 0.0
                    self._chase(dt, tile_map)
        elif self.path:
            self._state = "run"
            self._move_along_path(dt)
        else:
            self._state = "idle"

        self._tick_animation(dt)
        return spawned

    # ------------------------------------------------------------------
    # Overridable hooks
    # ------------------------------------------------------------------

    def _pre_state_tick(self, dt: float):
        """Return a list to short-circuit the state machine (caller returns it
        immediately). Implementations that return non-None must call
        _tick_animation() themselves. Return None to proceed normally."""
        return None

    def _on_enter_attack(self):
        """Called each frame the unit is within attack range of its target."""
        pass

    def _tick_attack(self, dt: float):
        """Perform one attack frame. Return a projectile to spawn, or None."""
        raise NotImplementedError

    def _current_anim_key(self) -> str:
        return self._state

    # ------------------------------------------------------------------
    # Animation
    # ------------------------------------------------------------------

    def _tick_animation(self, dt: float):
        self._anim_key    = self._current_anim_key()
        self._anim_timer += dt
        if self._anim_timer >= 1.0 / ANIM_FPS:
            self._anim_timer -= 1.0 / ANIM_FPS
            count = self.FRAME_COUNTS[self._anim_key]
            if self._state == "attack" and self._frame_idx >= count - 1:
                pass  # hold last frame until next swing resets to 0
            else:
                self._frame_idx = (self._frame_idx + 1) % count
