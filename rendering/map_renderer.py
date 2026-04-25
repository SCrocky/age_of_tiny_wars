from __future__ import annotations
import math
import pygame
from pygame._sdl2.video import Renderer, Texture
from map import TILE_SIZE, WATER, GRASS
import assets
import texture_cache


class MapRenderer:
    """Owns the tile texture and renders a TileMap to the screen via the GPU renderer."""

    _SHEET_COLS  = 9
    _SHEET_ROWS  = 6
    _GRASS_COLOR = (106, 153, 56)
    _WATER_COLOR = (56, 120, 153)

    def __init__(self) -> None:
        self._tile_cache:  pygame.Surface | None = None
        self._tile_tex:    Texture | None        = None   # GPU texture, rebuilt with tile cache
        self._water_tile:  pygame.Surface | None = None
        self._sheet_tiles: list[pygame.Surface]  = []
        self._loaded = False

        self._fog_surf: pygame.Surface | None = None
        self._fog_tex:  Texture | None        = None   # streaming texture for fog overlay

        _FOG_GRID = TILE_SIZE // 2
        self._FOG_GRID = _FOG_GRID
        self._drawn_footprints: set[tuple[int, int, int]] = set()
        self._explored_tile_surf:  pygame.Surface | None = None
        self._explored_vp_surf:    pygame.Surface | None = None
        self._explored_vp_key:     tuple | None          = None

        self._renderer: Renderer | None = None

    # ------------------------------------------------------------------

    def _load_sprites(self) -> None:
        self._water_tile = assets.load_image(
            "assets/Terrain/Tileset/Water Background color.png"
        )

        sheet = assets.load_image(
            "assets/Terrain/Tileset/Tilemap_color1.png"
        )
        self._sheet_tiles = []
        for row in range(self._SHEET_ROWS):
            for col in range(self._SHEET_COLS):
                tile = sheet.subsurface(
                    pygame.Rect(col * TILE_SIZE, row * TILE_SIZE, TILE_SIZE, TILE_SIZE)
                )
                self._sheet_tiles.append(tile)

        self._loaded = True

    def _build_tile_cache(self, tile_map) -> None:
        """Pre-render all tiles into a Surface then upload as a GPU Texture."""
        surf = pygame.Surface((tile_map.pixel_width, tile_map.pixel_height))
        for row in range(tile_map.rows):
            for col in range(tile_map.cols):
                x = col * TILE_SIZE
                y = row * TILE_SIZE
                if tile_map.tiles[row][col] == WATER:
                    surf.blit(self._water_tile, (x, y))
                else:
                    pygame.draw.rect(surf, self._GRASS_COLOR,
                                     (x, y, TILE_SIZE + 1, TILE_SIZE + 1))
        self._tile_cache = surf
        self._tile_tex   = Texture.from_surface(self._renderer, surf)
        tile_map._tiles_dirty = False

    # ------------------------------------------------------------------

    def render(self, tile_map, renderer: Renderer, camera) -> None:
        self._renderer = renderer

        if not self._loaded:
            self._load_sprites()

        if self._tile_cache is None or tile_map._tiles_dirty:
            self._build_tile_cache(tile_map)

        zoom = camera.zoom
        sw   = camera.screen_width
        sh   = camera.screen_height

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

        # GPU handles the viewport crop + scale — no CPU transform.scale needed.
        self._tile_tex.draw(
            srcrect=(src_x, src_y, src_w, src_h),
            dstrect=(dst_x, dst_y, dst_w, dst_h),
        )

    def render_fog(self, fog, tile_map, renderer: Renderer, camera,
                   reveal_entities=()) -> None:
        sw   = camera.screen_width
        sh   = camera.screen_height
        zoom = camera.zoom
        ts   = TILE_SIZE
        G    = self._FOG_GRID
        cols = tile_map.cols
        rows = tile_map.rows

        if self._fog_surf is None or self._fog_surf.get_size() != (sw, sh):
            self._fog_surf = pygame.Surface((sw, sh), pygame.SRCALPHA)

        # Incrementally add newly-explored footprints to the tile-resolution surface.
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
            self._explored_vp_key = None

        src_x  = max(0, int(camera.x / ts))
        src_y  = max(0, int(camera.y / ts))
        src_x2 = min(cols, int(math.ceil((camera.x + sw / zoom) / ts)) + 1)
        src_y2 = min(rows, int(math.ceil((camera.y + sh / zoom) / ts)) + 1)
        src_w  = max(1, src_x2 - src_x)
        src_h  = max(1, src_y2 - src_y)

        dst_x = int((src_x * ts - camera.x) * zoom)
        dst_y = int((src_y * ts - camera.y) * zoom)
        dst_w = max(1, int(src_w * ts * zoom))
        dst_h = max(1, int(src_h * ts * zoom))

        vp_key = (src_x, src_y, src_w, src_h, dst_w, dst_h)
        if vp_key != self._explored_vp_key and self._explored_tile_surf is not None:
            sub = self._explored_tile_surf.subsurface(
                pygame.Rect(src_x, src_y, src_w, src_h)
            )
            if (self._explored_vp_surf is None
                    or self._explored_vp_surf.get_size() != (dst_w, dst_h)):
                self._explored_vp_surf = pygame.Surface((dst_w, dst_h), pygame.SRCALPHA)
            pygame.transform.scale(sub, (dst_w, dst_h), self._explored_vp_surf)
            self._explored_vp_key = vp_key

        fog_surf = self._fog_surf
        fog_surf.fill((0, 0, 0, 255))
        clip = pygame.Rect(dst_x, dst_y, dst_w, dst_h).clip(fog_surf.get_rect())
        if clip.width > 0 and clip.height > 0 and self._explored_vp_surf is not None:
            evp_sub = self._explored_vp_surf.subsurface(
                pygame.Rect(clip.x - dst_x, clip.y - dst_y, clip.w, clip.h)
            )
            pygame.transform.scale(evp_sub, (clip.w, clip.h), fog_surf.subsurface(clip))

        for entity in reveal_entities:
            if not getattr(entity, "alive", True):
                continue
            sx, sy = camera.world_to_screen(entity.x, entity.y)
            radius = int(getattr(entity, "VISION_RADIUS", 5) * ts * zoom)
            pygame.draw.circle(fog_surf, (0, 0, 0, 0), (int(sx), int(sy)), radius)

        # Upload the CPU fog surface to a streaming GPU texture and draw it.
        if self._fog_tex is None or self._fog_tex.width != sw or self._fog_tex.height != sh:
            self._fog_tex = Texture(renderer, (sw, sh), streaming=True)
            self._fog_tex.blend_mode = pygame.BLENDMODE_BLEND
        self._fog_tex.update(self._fog_surf)
        self._fog_tex.draw()
