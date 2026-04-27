"""
Bottom-left minimap.

Reuses the GPU tile texture from MapRenderer for the background, paints
coloured dots for visible entities, draws the camera's viewport rect,
and exposes hit_test() for click/drag-to-pan.
"""
from __future__ import annotations
import pygame
from pygame._sdl2.video import Renderer

_BUILDING_TYPES = ("Castle", "Archery", "Barracks", "House", "Tower", "Monastery")
_RESOURCE_COLORS = {
    "GoldNode": (255, 200, 80),
    "WoodNode": (140, 90,  50),
    "MeatNode": (220, 220, 220),
}


class Minimap:
    MAX_SIZE = 220
    PAD      = 8
    BG_COLOR = (20, 30, 50, 255)
    BORDER   = (200, 180, 120, 255)

    def __init__(self, window_w: int, window_h: int):
        self.window_w  = window_w
        self.window_h  = window_h
        self._scale    = 1.0
        self._w        = self.MAX_SIZE
        self._h        = self.MAX_SIZE
        self._x        = 0
        self._y        = 0
        self._laid_out = False

    def _layout(self, map_pw: int, map_ph: int) -> None:
        if self._laid_out:
            return
        s = self.MAX_SIZE / max(map_pw, map_ph)
        self._scale    = s
        self._w        = max(1, int(map_pw * s))
        self._h        = max(1, int(map_ph * s))
        self._x        = self.PAD
        self._y        = self.window_h - self._h - self.PAD
        self._laid_out = True

    # ------------------------------------------------------------------

    def draw(self, renderer: Renderer, tile_tex, map_pw: int, map_ph: int,
             camera, entities, player_team: str, fog_visible) -> None:
        self._layout(map_pw, map_ph)
        x, y, w, h = self._x, self._y, self._w, self._h

        renderer.draw_color = self.BG_COLOR
        renderer.fill_rect(pygame.Rect(x, y, w, h))

        if tile_tex is not None:
            tile_tex.draw(dstrect=(x, y, w, h))

        for e in entities:
            if not getattr(e, "alive", True):
                continue
            if not fog_visible(e):
                continue
            t = type(e).__name__
            ex = x + int(e.x * self._scale)
            ey = y + int(e.y * self._scale)
            if not (x <= ex < x + w and y <= ey < y + h):
                continue
            color = self._color_for(t, getattr(e, "team", None), player_team)
            size  = 4 if t in _BUILDING_TYPES else 2
            renderer.draw_color = color
            renderer.fill_rect(pygame.Rect(ex - size // 2, ey - size // 2, size, size))

        cx = x + int(camera.x * self._scale)
        cy = y + int(camera.y * self._scale)
        cw = int(camera.screen_width  / camera.zoom * self._scale)
        ch = int(camera.screen_height / camera.zoom * self._scale)
        cx2 = min(cx + cw, x + w)
        cy2 = min(cy + ch, y + h)
        cx  = max(cx, x)
        cy  = max(cy, y)
        if cx2 > cx and cy2 > cy:
            renderer.draw_color = (255, 255, 255, 255)
            renderer.draw_rect(pygame.Rect(cx, cy, cx2 - cx, cy2 - cy))

        renderer.draw_color = self.BORDER
        renderer.draw_rect(pygame.Rect(x - 1, y - 1, w + 2, h + 2))
        renderer.draw_rect(pygame.Rect(x - 2, y - 2, w + 4, h + 4))

    # ------------------------------------------------------------------

    def hit_test(self, mx: int, my: int, map_pw: int, map_ph: int) -> tuple[float, float] | None:
        self._layout(map_pw, map_ph)
        if not (self._x <= mx < self._x + self._w
                and self._y <= my < self._y + self._h):
            return None
        return (mx - self._x) / self._scale, (my - self._y) / self._scale

    # ------------------------------------------------------------------

    @staticmethod
    def _color_for(type_name: str, team, player_team: str) -> tuple[int, int, int, int]:
        if type_name in _RESOURCE_COLORS:
            r, g, b = _RESOURCE_COLORS[type_name]
            return (r, g, b, 255)
        if team == player_team:
            return (80, 200, 255, 255)
        return (220, 80, 80, 255)
