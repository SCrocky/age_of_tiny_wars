import pygame

# surface id → {(w, h, flip_x, flip_y): scaled_surface}
_cache: dict[int, dict[tuple, pygame.Surface]] = {}

# surface id → {(w, h, angle): rotated_surface}
_rot_cache: dict[int, dict[tuple, pygame.Surface]] = {}

# font size → pygame.Font
_font_cache: dict[int, pygame.font.Font] = {}


def get_scaled(surf: pygame.Surface, w: int, h: int,
               flip_x: bool = False, flip_y: bool = False) -> pygame.Surface:
    sid = id(surf)
    key = (w, h, flip_x, flip_y)
    entry = _cache.get(sid)
    if entry is None:
        _cache[sid] = entry = {}
    cached = entry.get(key)
    if cached is None:
        s = pygame.transform.scale(surf, (w, h))
        if flip_x or flip_y:
            s = pygame.transform.flip(s, flip_x, flip_y)
        entry[key] = cached = s
    return cached


def get_scaled_rotated(surf: pygame.Surface, size: int, angle: float) -> pygame.Surface:
    """Scale to size×size then rotate; both operations are cached together."""
    sid = id(surf)
    key = (size, angle)
    entry = _rot_cache.get(sid)
    if entry is None:
        _rot_cache[sid] = entry = {}
    cached = entry.get(key)
    if cached is None:
        scaled = pygame.transform.scale(surf, (size, size))
        entry[key] = cached = pygame.transform.rotate(scaled, angle)
    return cached


def get_font(size: int) -> pygame.font.Font:
    font = _font_cache.get(size)
    if font is None:
        _font_cache[size] = font = pygame.font.SysFont(None, size)
    return font
