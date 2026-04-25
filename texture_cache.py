"""GPU texture cache for the pygame-ce SDL2 hardware renderer."""
import pygame
from pygame._sdl2.video import Renderer, Texture

_renderer: Renderer | None = None
_surf_to_tex: dict[int, Texture] = {}
_font_cache: dict[int, pygame.font.Font] = {}

_circle_tex: Texture | None = None
_CIRCLE_SIZE = 128


def init(renderer: Renderer) -> None:
    global _renderer, _circle_tex
    _renderer = renderer

    # Pre-render a white ring; color-modulated to yellow at draw time.
    surf = pygame.Surface((_CIRCLE_SIZE, _CIRCLE_SIZE), pygame.SRCALPHA)
    pygame.draw.circle(
        surf, (255, 255, 255, 255),
        (_CIRCLE_SIZE // 2, _CIRCLE_SIZE // 2),
        _CIRCLE_SIZE // 2 - 2, 3,
    )
    _circle_tex = Texture.from_surface(renderer, surf)
    _circle_tex.blend_mode = pygame.BLENDMODE_BLEND
    _circle_tex.color = (255, 220, 0)   # selection colour; never changes


def get_texture(surf: pygame.Surface) -> Texture:
    """Return the cached GPU Texture for a persistent surface, uploading once."""
    sid = id(surf)
    tex = _surf_to_tex.get(sid)
    if tex is None:
        tex = Texture.from_surface(_renderer, surf)
        tex.blend_mode = pygame.BLENDMODE_BLEND
        _surf_to_tex[sid] = tex
    return tex


def make_texture(surf: pygame.Surface) -> Texture:
    """Create a one-off (uncached) Texture — use for ephemeral surfaces."""
    tex = Texture.from_surface(_renderer, surf)
    tex.blend_mode = pygame.BLENDMODE_BLEND
    return tex


def get_font(size: int) -> pygame.font.Font:
    font = _font_cache.get(size)
    if font is None:
        _font_cache[size] = font = pygame.font.SysFont(None, size)
    return font


def get_circle_tex() -> Texture:
    return _circle_tex
