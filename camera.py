from __future__ import annotations
from dataclasses import dataclass

import pygame


class Viewport:
    """Maps the game's logical 1600×900 world into a centred sub-rect of the
    actual OS window, leaving any letterbox/pillarbox space free for HUD use."""

    def __init__(self, window_w: int, window_h: int,
                 logical_w: int, logical_h: int):
        scale = min(window_w / logical_w, window_h / logical_h)
        self.window_w  = window_w
        self.window_h  = window_h
        self.logical_w = logical_w
        self.logical_h = logical_h
        self.scale     = scale
        self.w         = int(logical_w * scale)
        self.h         = int(logical_h * scale)
        self.x         = (window_w - self.w) // 2
        self.y         = (window_h - self.h) // 2

    def to_logical(self, wx: float, wy: float) -> tuple[float, float]:
        return (wx - self.x) / self.scale, (wy - self.y) / self.scale

    def apply_world(self, renderer):
        renderer.set_viewport(pygame.Rect(self.x, self.y, self.w, self.h))
        renderer.scale = (self.scale, self.scale)

    def apply_window(self, renderer):
        renderer.set_viewport(pygame.Rect(0, 0, self.window_w, self.window_h))
        renderer.scale = (1.0, 1.0)


@dataclass
class InputSnapshot:
    """Polled input state for one frame. Created in game.py where pygame lives."""
    pan_left:  bool
    pan_right: bool
    pan_up:    bool
    pan_down:  bool
    mouse_x:   float
    mouse_y:   float


class Camera:
    PAN_SPEED          = 500   # world pixels per second
    ZOOM_STEP          = 0.1
    MIN_ZOOM           = 0.05
    MAX_ZOOM           = 3.0
    EDGE_SCROLL_MARGIN = 20    # px from screen edge that triggers scrolling

    def __init__(self, screen_width: int, screen_height: int):
        self.x             = 0.0
        self.y             = 0.0
        self.zoom          = 1.0
        self.screen_width  = screen_width
        self.screen_height = screen_height

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def update(self, dt: float, map_pixel_width: int, map_pixel_height: int,
               inp: InputSnapshot):
        speed = self.PAN_SPEED / self.zoom * dt

        if inp.pan_left:  self.x -= speed
        if inp.pan_right: self.x += speed
        if inp.pan_up:    self.y -= speed
        if inp.pan_down:  self.y += speed

        m = self.EDGE_SCROLL_MARGIN
        if inp.mouse_x < m:                        self.x -= speed
        if inp.mouse_x > self.screen_width  - m:   self.x += speed
        if inp.mouse_y < m:                        self.y -= speed
        if inp.mouse_y > self.screen_height - m:   self.y += speed

        max_x = max(0.0, map_pixel_width  - self.screen_width  / self.zoom)
        max_y = max(0.0, map_pixel_height - self.screen_height / self.zoom)
        self.x = max(0.0, min(self.x, max_x))
        self.y = max(0.0, min(self.y, max_y))

    def zoom_at(self, screen_x: float, screen_y: float, direction: int):
        """Zoom in/out keeping the point under the cursor fixed in world space."""
        wx_before, wy_before = self.screen_to_world(screen_x, screen_y)

        self.zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM,
                        self.zoom + direction * self.ZOOM_STEP))

        wx_after, wy_after = self.screen_to_world(screen_x, screen_y)
        self.x += wx_before - wx_after
        self.y += wy_before - wy_after

    # ------------------------------------------------------------------
    # Coordinate conversion (pure math)
    # ------------------------------------------------------------------

    def world_to_screen(self, wx: float, wy: float) -> tuple[float, float]:
        return (wx - self.x) * self.zoom, (wy - self.y) * self.zoom

    def screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        return sx / self.zoom + self.x, sy / self.zoom + self.y
