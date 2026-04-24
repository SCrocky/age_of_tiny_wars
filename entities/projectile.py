import math

ARROW_SPEED      = 400.0  # world px / second
ARROW_DAMAGE     = 15
ARROW_HIT_RADIUS = 12.0   # world px — snap-to-hit distance


class Arrow:
    """A projectile fired by an Archer at a target entity."""

    def __init__(self, x: float, y: float, target, damage: int, team: str,
                 speed: float = ARROW_SPEED):
        self.entity_id: int = 0
        self.x      = x
        self.y      = y
        self.target = target   # Entity reference — we home on it
        self.damage = damage
        self.team   = team
        self.alive  = True
        self._speed = speed

        dx = target.x - x
        dy = target.y - y
        self._angle = math.degrees(math.atan2(-dy, dx))

    def update(self, dt: float):
        if not self.alive:
            return

        if not self.target.alive:
            self.alive = False
            return

        dx   = self.target.x - self.x
        dy   = self.target.y - self.y
        dist = math.hypot(dx, dy)

        if dist <= ARROW_HIT_RADIUS:
            self.target.take_damage(self.damage)
            self.alive = False
            return

        self._angle = math.degrees(math.atan2(-dy, dx))
        speed = self._speed * dt
        self.x += dx / dist * speed
        self.y += dy / dist * speed
