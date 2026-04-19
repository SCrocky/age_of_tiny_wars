import math
import pygame
from entities.entity import Entity


class Building(Entity):
    """Base class for all static structures."""

    DISPLAY_W   = 64
    DISPLAY_H   = 64
    COLLISION_W = DISPLAY_W
    COLLISION_H = DISPLAY_H
    is_depot    = False
    pop_bonus   = 0

    def __init__(self, x: float, y: float, team: str, max_hp: int = 200):
        super().__init__(x, y, team, max_hp)

    def closest_point(self, x: float, y: float) -> tuple[float, float]:
        hw = self.COLLISION_W / 2
        hh = self.COLLISION_H / 2
        return (
            max(self.x - hw, min(x, self.x + hw)),
            max(self.y - hh, min(y, self.y + hh)),
        )

    def hit_test(self, sx: float, sy: float, camera) -> bool:
        ux, uy = camera.world_to_screen(self.x, self.y)
        hw = self.DISPLAY_W * camera.zoom / 2
        hh = self.DISPLAY_H * camera.zoom / 2
        return abs(sx - ux) <= hw and abs(sy - uy) <= hh

    def render(self, surface: pygame.Surface, camera):
        raise NotImplementedError


# ---------------------------------------------------------------------------


class Archery(Building):
    DISPLAY_W   = 192
    DISPLAY_H   = 192
    COLLISION_W = 140
    COLLISION_H = 100

    def __init__(self, x: float, y: float, team: str):
        super().__init__(x, y, team, max_hp=300)
        path = f"assets/Buildings/{team.capitalize()} Buildings/Archery.png"
        self._surf = pygame.image.load(path).convert_alpha()

    def render(self, surface: pygame.Surface, camera):
        if not self.alive:
            return
        w = max(1, int(self.DISPLAY_W * camera.zoom))
        h = max(1, int(self.DISPLAY_H * camera.zoom))
        scaled = pygame.transform.scale(self._surf, (w, h))
        sx, sy = camera.world_to_screen(self.x, self.y)
        surface.blit(scaled, (int(sx - w / 2), int(sy - h / 2)))
        if self.selected:
            pygame.draw.rect(surface, (255, 220, 0),
                             (int(sx - w / 2), int(sy - h / 2), w, h), 2)
        self.draw_health_bar(surface, camera, width=60)


class Barracks(Building):
    DISPLAY_W   = 192
    DISPLAY_H   = 192
    COLLISION_W = 140
    COLLISION_H = 100

    def __init__(self, x: float, y: float, team: str):
        super().__init__(x, y, team, max_hp=350)
        path = f"assets/Buildings/{team.capitalize()} Buildings/Barracks.png"
        self._surf = pygame.image.load(path).convert_alpha()

    def render(self, surface: pygame.Surface, camera):
        if not self.alive:
            return
        w = max(1, int(self.DISPLAY_W * camera.zoom))
        h = max(1, int(self.DISPLAY_H * camera.zoom))
        scaled = pygame.transform.scale(self._surf, (w, h))
        sx, sy = camera.world_to_screen(self.x, self.y)
        surface.blit(scaled, (int(sx - w / 2), int(sy - h / 2)))
        if self.selected:
            pygame.draw.rect(surface, (255, 220, 0),
                             (int(sx - w / 2), int(sy - h / 2), w, h), 2)
        self.draw_health_bar(surface, camera, width=60)


class House(Building):
    DISPLAY_W   = 128
    DISPLAY_H   = 128
    COLLISION_W = 90
    COLLISION_H = 70
    is_depot    = True
    pop_bonus   = 5

    def __init__(self, x: float, y: float, team: str, variant: int = 1):
        super().__init__(x, y, team, max_hp=150)
        n = max(1, min(3, variant))
        path = f"assets/Buildings/{team.capitalize()} Buildings/House{n}.png"
        self._surf = pygame.image.load(path).convert_alpha()

    def render(self, surface: pygame.Surface, camera):
        if not self.alive:
            return
        w = max(1, int(self.DISPLAY_W * camera.zoom))
        h = max(1, int(self.DISPLAY_H * camera.zoom))
        scaled = pygame.transform.scale(self._surf, (w, h))
        sx, sy = camera.world_to_screen(self.x, self.y)
        surface.blit(scaled, (int(sx - w / 2), int(sy - h / 2)))
        if self.selected:
            pygame.draw.rect(surface, (255, 220, 0),
                             (int(sx - w / 2), int(sy - h / 2), w, h), 2)
        self.draw_health_bar(surface, camera, width=50)


class Castle(Building):
    DISPLAY_W   = 320
    DISPLAY_H   = 256
    COLLISION_W = 220
    COLLISION_H = 100
    is_depot    = True
    pop_bonus   = 10

    def __init__(self, x: float, y: float, team: str):
        super().__init__(x, y, team, max_hp=500)

        path = f"assets/Buildings/{team.capitalize()} Buildings/Castle.png"
        self._surf = pygame.image.load(path).convert_alpha()

    def render(self, surface: pygame.Surface, camera):
        if not self.alive:
            return

        w = max(1, int(self.DISPLAY_W * camera.zoom))
        h = max(1, int(self.DISPLAY_H * camera.zoom))
        scaled = pygame.transform.scale(self._surf, (w, h))
        sx, sy = camera.world_to_screen(self.x, self.y)
        surface.blit(scaled, (int(sx - w / 2), int(sy - h / 2)))

        if self.selected:
            pygame.draw.rect(
                surface, (255, 220, 0),
                (int(sx - w / 2), int(sy - h / 2), w, h), 2,
            )

        self.draw_health_bar(surface, camera, width=80)


