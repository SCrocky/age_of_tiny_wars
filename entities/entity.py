class Entity:
    """Base class for all game objects with a world position and health."""

    VISION_RADIUS = 5  # tiles

    def __init__(self, x: float, y: float, team: str, max_hp: int = 100):
        self.entity_id: int = 0
        self.x = x          # world-space centre
        self.y = y
        self.team = team    # e.g. 'blue', 'black'
        self.max_hp = max_hp
        self.hp = max_hp
        self.selected = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def sort_y(self) -> float:
        return self.y

    def closest_point(self, x: float, y: float) -> tuple[float, float]:
        return self.x, self.y

    def take_damage(self, amount: int, is_melee: bool = False):
        self.hp -= amount

    def receive_melee_hit(self, attacker):
        """Called when struck by a melee attack. Override to react (e.g. play defence animation)."""
        pass
