from entities.building import Archery, Barracks, House, Tower

BUILD_RATE = 30.0  # HP-equivalent progress per second per builder

# name → (class, cost_dict)
BUILDABLE: dict[str, tuple[type, dict[str, int]]] = {
    "Archery":  (Archery,  {"wood": 30, "gold": 20}),
    "Barracks": (Barracks, {"wood": 50, "gold": 30}),
    "House":    (House,    {"wood": 20}),
    "Tower":    (Tower,    {"wood": 100}),
}


class Blueprint:
    """A building site under construction. Wraps a pre-created building instance."""

    def __init__(self, building):
        self._building   = building
        self.x           = building.x
        self.y           = building.y
        self.team        = building.team
        self.selected    = False
        self.alive       = True
        self.progress    = 0.0
        self.COLLISION_W = building.COLLISION_W
        self.COLLISION_H = building.COLLISION_H

    @property
    def hp(self) -> int:
        return int(self.progress)

    @property
    def max_hp(self) -> int:
        return self._building.max_hp

    @property
    def sort_y(self) -> float:
        return self._building.sort_y

    def closest_point(self, x: float, y: float) -> tuple[float, float]:
        return self._building.closest_point(x, y)

    def hit_test(self, sx: float, sy: float, camera) -> bool:
        return self._building.hit_test(sx, sy, camera)

    def add_progress(self, amount: float) -> bool:
        """Returns True when construction completes."""
        self.progress = min(self._building.max_hp, self.progress + amount)
        return self.progress >= self._building.max_hp

    def complete(self):
        """Mark done and return the finished building."""
        self.alive = False
        return self._building
