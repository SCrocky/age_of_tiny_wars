import pygame


class Entity:
    """Base class for all game objects with a world position and health."""

    def __init__(self, x: float, y: float, team: str, max_hp: int = 100):
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

    def receive_melee_hit(self, attacker):
        """Called when struck by a melee attack. Override to react (e.g. play defence animation)."""
        pass

    def draw_health_bar(self, surface: pygame.Surface, camera, width: int = 40, force: bool = False):
        # Only show health bar when selected or damaged
        if not force and not self.selected and self.hp == self.max_hp:
            return

        sx, sy = camera.world_to_screen(self.x, self.y)
        bar_w = int(width * camera.zoom)
        bar_h = max(3, int(4 * camera.zoom))
        bx = int(sx - bar_w / 2)
        by = int(sy - int(36 * camera.zoom))          # above the sprite

        pygame.draw.rect(surface, (80, 0, 0),   (bx, by, bar_w, bar_h))
        fill = int(bar_w * self.hp / self.max_hp)
        pygame.draw.rect(surface, (0, 200, 60), (bx, by, fill,  bar_h))
        pygame.draw.rect(surface, (0, 0, 0),    (bx, by, bar_w, bar_h), 1)
