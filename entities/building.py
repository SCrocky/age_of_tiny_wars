import pygame


class Castle:
    """
    Static building that acts as a drop-off point for gathered resources.
    One per team; placed at a fixed world position.
    """

    DISPLAY_W = 320  # render width  (sprite is 320×256)
    DISPLAY_H = 256  # render height (maintains aspect ratio)
    DEPOSIT_RADIUS = (
        210.0  # world px — must exceed the blocked zone radius (2 tiles = 192 px)
    )

    def __init__(self, x: float, y: float, team: str):
        self.x = x  # world-space centre
        self.y = y
        self.team = team

        path = f"assets/Buildings/{team.capitalize()} Buildings/Castle.png"
        self._surf = pygame.image.load(path).convert_alpha()

    # ------------------------------------------------------------------

    def render(self, surface: pygame.Surface, camera):
        w = max(1, int(self.DISPLAY_W * camera.zoom))
        h = max(1, int(self.DISPLAY_H * camera.zoom))
        scaled = pygame.transform.scale(self._surf, (w, h))
        sx, sy = camera.world_to_screen(self.x, self.y)
        surface.blit(scaled, (int(sx - w / 2), int(sy - h / 2)))

    def is_near(self, x: float, y: float) -> bool:
        import math
        return math.hypot(x - self.x, y - self.y) <= self.DEPOSIT_RADIUS

    def hit_test(self, sx: float, sy: float, camera) -> bool:
        ux, uy = camera.world_to_screen(self.x, self.y)
        hw = self.DISPLAY_W * camera.zoom / 2
        hh = self.DISPLAY_H * camera.zoom / 2
        return abs(sx - ux) <= hw and abs(sy - uy) <= hh
