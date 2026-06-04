"""
Bottom-left minimap.

Reuses the GPU tile texture from MapRenderer for the background, paints
coloured dots for visible entities, draws the camera's viewport rect,
and exposes hit_test() for click/drag-to-pan.
"""
from __future__ import annotations
import numpy as np
import pygame
import pygame.surfarray as surfarray
from pygame._sdl2.video import Renderer, Texture
from systems.fog import UNEXPLORED

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
        self._laid_out    = False
        self._fog_tex     = None   # cached Texture of the fog overlay
        self._fog_version = -1     # FogOfWar.version when _fog_tex was built
        self._fog_dims    = None   # (cols, rows) when index arrays were built
        self._fog_idx     = None   # (col_idx, row_idx) numpy arrays, cached

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

    def _build_fog_tex(self, renderer: Renderer, fog, tile_size: int) -> Texture:
        """Rebuild the fog overlay texture from current FogOfWar state."""
        w, h = self._w, self._h
        ts   = tile_size * self._scale

        if self._fog_dims != (fog.cols, fog.rows):
            self._fog_dims = (fog.cols, fog.rows)
            self._fog_idx  = (
                np.minimum((np.arange(w) / ts).astype(np.int32), fog.cols - 1),
                np.minimum((np.arange(h) / ts).astype(np.int32), fog.rows - 1),
            )
        col_idx, row_idx = self._fog_idx

        # Sample in (w, h) layout directly — no transpose or ascontiguousarray needed.
        # result[x, y] = fog_2d[row_idx[y], col_idx[x]]
        fog_2d    = np.frombuffer(fog._state, dtype=np.uint8).reshape(fog.rows, fog.cols)
        state_map = fog_2d[row_idx[np.newaxis, :], col_idx[:, np.newaxis]]  # (w, h)

        # LUT: UNEXPLORED→black opaque, EXPLORED→dark green semi-transparent, VISIBLE→clear
        lut  = np.array([(0, 0, 0, 255), (20, 35, 20, 170), (0, 0, 0, 0)], dtype=np.uint8)
        rgba = lut[np.clip(state_map, 0, 2)]   # (w, h, 4) — already in surfarray layout

        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        pix = surfarray.pixels3d(surf)
        pix[:] = rgba[:, :, :3]
        del pix
        alp = surfarray.pixels_alpha(surf)
        alp[:] = rgba[:, :, 3]
        del alp

        # Reuse a single streaming texture to avoid GPU reallocation every rebuild.
        if (self._fog_tex is None
                or self._fog_tex.width != w or self._fog_tex.height != h):
            self._fog_tex = Texture(renderer, (w, h), streaming=True)
            self._fog_tex.blend_mode = pygame.BLENDMODE_BLEND
        self._fog_tex.update(surf)
        return self._fog_tex

    # ------------------------------------------------------------------

    def draw(self, renderer: Renderer, tile_tex, map_pw: int, map_ph: int,
             camera, entities, player_team: str, fog_visible,
             fog=None, tile_size: int = 64) -> None:
        self._layout(map_pw, map_ph)
        x, y, w, h = self._x, self._y, self._w, self._h

        renderer.draw_color = self.BG_COLOR
        renderer.fill_rect(pygame.Rect(x, y, w, h))

        if tile_tex is not None:
            tile_tex.draw(dstrect=(x, y, w, h))

        if fog is not None:
            if fog.version != self._fog_version:
                self._fog_tex     = self._build_fog_tex(renderer, fog, tile_size)
                self._fog_version = fog.version
            if self._fog_tex is not None:
                self._fog_tex.draw(dstrect=(x, y, w, h))

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
