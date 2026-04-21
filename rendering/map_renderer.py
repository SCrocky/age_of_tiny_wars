from __future__ import annotations
import math
import pygame
from map import TILE_SIZE, WATER, GRASS


class MapRenderer:
    """Owns the tile Surface cache and renders a TileMap to the screen."""

    _SHEET_COLS  = 9
    _SHEET_ROWS  = 6
    _GRASS_COLOR = (106, 153, 56)
    _WATER_COLOR = (56, 120, 153)

    def __init__(self) -> None:
        self._tile_cache:  pygame.Surface | None   = None
        self._water_tile:  pygame.Surface | None   = None
        self._sheet_tiles: list[pygame.Surface]    = []
        self._loaded = False
        self._vp_key:  tuple | None          = None
        self._vp_surf: pygame.Surface | None = None
        self._fog_surf: pygame.Surface | None = None
        _FOG_GRID = TILE_SIZE // 2   # footprint granularity: half a tile
        self._FOG_GRID = _FOG_GRID
        # Footprints already drawn onto _explored_tile_surf — only new ones trigger a draw
        self._drawn_footprints: set[tuple[int, int, int]] = set()
        # Tile-resolution surface (250×150px); updated incrementally, never fully rebuilt
        self._explored_tile_surf:  pygame.Surface | None = None
        # Scaled viewport surface (rebuilt only when the tile region or zoom changes)
        self._explored_vp_surf: pygame.Surface | None = None
        self._explored_vp_key:  tuple | None = None

    # ------------------------------------------------------------------

    def _load_sprites(self) -> None:
        self._water_tile = pygame.image.load(
            "assets/Terrain/Tileset/Water Background color.png"
        ).convert_alpha()

        sheet = pygame.image.load(
            "assets/Terrain/Tileset/Tilemap_color1.png"
        ).convert_alpha()
        self._sheet_tiles = []
        for row in range(self._SHEET_ROWS):
            for col in range(self._SHEET_COLS):
                tile = sheet.subsurface(
                    pygame.Rect(col * TILE_SIZE, row * TILE_SIZE, TILE_SIZE, TILE_SIZE)
                )
                self._sheet_tiles.append(tile)

        self._loaded = True

    def _build_tile_cache(self, tile_map) -> None:
        """Pre-render all tiles into a full-resolution Surface (zoom=1.0)."""
        surf = pygame.Surface((tile_map.pixel_width, tile_map.pixel_height))
        for row in range(tile_map.rows):
            for col in range(tile_map.cols):
                x = col * TILE_SIZE
                y = row * TILE_SIZE
                if tile_map.tiles[row][col] == WATER:
                    surf.blit(self._water_tile, (x, y))
                else:
                    # +1 to eliminate sub-pixel gaps when scaled
                    pygame.draw.rect(surf, self._GRASS_COLOR,
                                     (x, y, TILE_SIZE + 1, TILE_SIZE + 1))
        self._tile_cache      = surf
        tile_map._tiles_dirty = False
        self._vp_key          = None  # invalidate viewport cache

    # ------------------------------------------------------------------

    def render(self, tile_map, surface: pygame.Surface, camera) -> None:
        if not self._loaded:
            self._load_sprites()

        if self._tile_cache is None or tile_map._tiles_dirty:
            self._build_tile_cache(tile_map)

        zoom = camera.zoom
        sw   = surface.get_width()
        sh   = surface.get_height()

        src_x  = max(0, int(camera.x))
        src_y  = max(0, int(camera.y))
        src_x2 = min(tile_map.pixel_width,  int(math.ceil(camera.x + sw / zoom)) + 1)
        src_y2 = min(tile_map.pixel_height, int(math.ceil(camera.y + sh / zoom)) + 1)
        src_w  = max(1, src_x2 - src_x)
        src_h  = max(1, src_y2 - src_y)

        dst_x = int((src_x - camera.x) * zoom)
        dst_y = int((src_y - camera.y) * zoom)
        dst_w = max(1, int(src_w * zoom))
        dst_h = max(1, int(src_h * zoom))

        vp_key = (src_x, src_y, src_w, src_h, dst_w, dst_h)
        if vp_key != self._vp_key:
            sub = self._tile_cache.subsurface((src_x, src_y, src_w, src_h))
            self._vp_surf = pygame.transform.scale(sub, (dst_w, dst_h))
            self._vp_key  = vp_key
        surface.blit(self._vp_surf, (dst_x, dst_y))

    def render_fog(self, fog, tile_map, surface: pygame.Surface, camera,
                   reveal_entities=()) -> None:
        sw   = surface.get_width()
        sh   = surface.get_height()
        zoom = camera.zoom
        ts   = TILE_SIZE
        G    = self._FOG_GRID
        cols = tile_map.cols
        rows = tile_map.rows

        if self._fog_surf is None or self._fog_surf.get_size() != (sw, sh):
            self._fog_surf = pygame.Surface((sw, sh), pygame.SRCALPHA)

        # Draw any newly-explored footprints directly onto the tile surface.
        # The surface is never fully rebuilt — only new circles are added.
        tile_surf_dirty = False
        for entity in reveal_entities:
            if not getattr(entity, "alive", True):
                continue
            r  = getattr(entity, "VISION_RADIUS", 5)
            fp = (int(entity.x / G), int(entity.y / G), r)
            if fp not in self._drawn_footprints:
                if self._explored_tile_surf is None:
                    self._explored_tile_surf = pygame.Surface((cols, rows), pygame.SRCALPHA)
                    self._explored_tile_surf.fill((0, 0, 0, 255))
                tx = int(fp[0] * G / ts)
                ty = int(fp[1] * G / ts)
                pygame.draw.circle(self._explored_tile_surf, (0, 0, 0, 160), (tx, ty), r)
                self._drawn_footprints.add(fp)
                tile_surf_dirty = True
        if tile_surf_dirty:
            self._explored_vp_key = None  # invalidate viewport cache

        # Tile indices covering the viewport (one extra on each side so sub-tile
        # offset never exposes an un-rendered edge).
        src_x  = max(0, int(camera.x / ts))
        src_y  = max(0, int(camera.y / ts))
        src_x2 = min(cols, int(math.ceil((camera.x + sw / zoom) / ts)) + 1)
        src_y2 = min(rows, int(math.ceil((camera.y + sh / zoom) / ts)) + 1)
        src_w  = max(1, src_x2 - src_x)
        src_h  = max(1, src_y2 - src_y)

        # Screen-space position and size of that tile block — mirrors render().
        dst_x = int((src_x * ts - camera.x) * zoom)   # ≤ 0 when camera is mid-tile
        dst_y = int((src_y * ts - camera.y) * zoom)
        dst_w = max(1, int(src_w * ts * zoom))
        dst_h = max(1, int(src_h * ts * zoom))

        # Rebuild the scaled explored surface only when the tile region or zoom changes.
        vp_key = (src_x, src_y, src_w, src_h, dst_w, dst_h)
        if vp_key != self._explored_vp_key:
            sub = self._explored_tile_surf.subsurface(
                pygame.Rect(src_x, src_y, src_w, src_h)
            )
            if (self._explored_vp_surf is None
                    or self._explored_vp_surf.get_size() != (dst_w, dst_h)):
                self._explored_vp_surf = pygame.Surface((dst_w, dst_h), pygame.SRCALPHA)
            pygame.transform.scale(sub, (dst_w, dst_h), self._explored_vp_surf)
            self._explored_vp_key = vp_key

        # Stamp the scaled surface into fog_surf at the correct sub-tile offset.
        # transform.scale into a subsurface does a direct pixel write (no alpha-composite).
        fog_surf = self._fog_surf
        fog_surf.fill((0, 0, 0, 255))   # default: fully opaque (unexplored/border)
        clip = pygame.Rect(dst_x, dst_y, dst_w, dst_h).clip(fog_surf.get_rect())
        if clip.width > 0 and clip.height > 0:
            evp_sub = self._explored_vp_surf.subsurface(
                pygame.Rect(clip.x - dst_x, clip.y - dst_y, clip.w, clip.h)
            )
            pygame.transform.scale(evp_sub, (clip.w, clip.h), fog_surf.subsurface(clip))

        # Punch transparent circles for currently visible entities
        for entity in reveal_entities:
            if not getattr(entity, "alive", True):
                continue
            sx, sy = camera.world_to_screen(entity.x, entity.y)
            radius = int(getattr(entity, "VISION_RADIUS", 5) * ts * zoom)
            pygame.draw.circle(fog_surf, (0, 0, 0, 0), (int(sx), int(sy)), radius)

        surface.blit(fog_surf, (0, 0))
