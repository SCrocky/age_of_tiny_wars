import math
import random

TILE_SIZE = 64  # world pixels per tile
NAV_TILE = 16   # navigation sub-grid cell size in world pixels
_NAV_SCALE = TILE_SIZE // NAV_TILE  # nav cells per tile edge (4)

# Tile type constants
WATER = 0
GRASS = 1


class TileMap:
    """
    A grid-based tile map.

    Tile types
    ----------
    WATER – rendered with the tiling water sprite
    GRASS – rendered with a grass terrain tile from the tileset sheet
    """

    def __init__(self, cols: int, rows: int):
        self.cols = cols
        self.rows = rows
        self.tiles:   list[list[int]]      = []
        self._tiles_dirty: bool            = True
        self._generate()

    @classmethod
    def from_data(cls, cols: int, rows: int, tiles: list[list[int]]) -> "TileMap":
        """Create a TileMap from a pre-built tile grid (skips procedural generation)."""
        obj = object.__new__(cls)
        obj.cols          = cols
        obj.rows          = rows
        obj.tiles         = [list(row) for row in tiles]
        obj._tiles_dirty  = True
        return obj

    # ------------------------------------------------------------------
    # Map generation
    # ------------------------------------------------------------------

    def _generate(self):
        """Generate a simple island: grass in the interior, water on the border."""
        border = 3

        self.tiles = []
        for row in range(self.rows):
            tile_row = []
            for col in range(self.cols):
                if (
                    col < border
                    or col >= self.cols - border
                    or row < border
                    or row >= self.rows - border
                ):
                    tile_row.append(WATER)
                else:
                    tile_row.append(GRASS)
            self.tiles.append(tile_row)

        rng = random.Random()
        for _ in range(8):
            lx = rng.randint(border + 1, self.cols - border - 4)
            ly = rng.randint(border + 1, self.rows - border - 4)
            lw = rng.randint(2, 4)
            lh = rng.randint(2, 3)
            for r in range(ly, min(ly + lh, self.rows - border)):
                for c in range(lx, min(lx + lw, self.cols - border)):
                    self.tiles[r][c] = WATER

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def pixel_width(self) -> int:
        return self.cols * TILE_SIZE

    @property
    def pixel_height(self) -> int:
        return self.rows * TILE_SIZE

    def tile_at(self, col: int, row: int) -> int:
        if 0 <= col < self.cols and 0 <= row < self.rows:
            return self.tiles[row][col]
        return WATER

    def is_walkable(self, col: int, row: int) -> bool:
        return self.tile_at(col, row) == GRASS

    def clear_area(self, world_x: float, world_y: float, tile_radius: int):
        """Force all tiles within tile_radius of a world position to GRASS."""
        cx = int(world_x // TILE_SIZE)
        cy = int(world_y // TILE_SIZE)
        for dr in range(-tile_radius, tile_radius + 1):
            for dc in range(-tile_radius, tile_radius + 1):
                col, row = cx + dc, cy + dr
                if 0 <= col < self.cols and 0 <= row < self.rows:
                    self.tiles[row][col] = GRASS
        self._tiles_dirty = True

    def nearest_walkable(self, col: int, row: int) -> tuple[int, int]:
        """Return the walkable tile closest to (col, row) by Euclidean distance."""
        if self.is_walkable(col, row):
            return col, row
        for r in range(1, 8):
            candidates = [
                (math.hypot(dc, dr), col + dc, row + dr)
                for dc in range(-r, r + 1)
                for dr in range(-r, r + 1)
                if (abs(dc) == r or abs(dr) == r)
                and self.is_walkable(col + dc, row + dr)
            ]
            if candidates:
                _, c, ro = min(candidates)
                return c, ro
        return col, row


class NavGrid:
    """
    Fine-grained navigation grid at NAV_TILE (16px) resolution.

    Initialized from a TileMap (water → blocked). Buildings and resources
    register their pixel footprints via block_rect / unblock_rect so A*
    routes around them.

    Convention: 0 = walkable, 1 = blocked.
    """

    def __init__(self, tile_map: "TileMap"):
        self._tile_map = tile_map
        self.cols = tile_map.cols * _NAV_SCALE
        self.rows = tile_map.rows * _NAV_SCALE
        self._blocked = bytearray(self.cols * self.rows)
        for tr in range(tile_map.rows):
            for tc in range(tile_map.cols):
                if not tile_map.is_walkable(tc, tr):
                    base_r = tr * _NAV_SCALE
                    base_c = tc * _NAV_SCALE
                    for nr in range(_NAV_SCALE):
                        row_off = (base_r + nr) * self.cols
                        for nc in range(_NAV_SCALE):
                            self._blocked[row_off + base_c + nc] = 1

    def is_walkable(self, col: int, row: int) -> bool:
        if col < 0 or col >= self.cols or row < 0 or row >= self.rows:
            return False
        return self._blocked[row * self.cols + col] == 0

    def _cell_range(self, x: float, y: float, w: float, h: float):
        c0 = max(0, int(x) // NAV_TILE)
        r0 = max(0, int(y) // NAV_TILE)
        c1 = min(self.cols - 1, int(x + w - 1) // NAV_TILE)
        r1 = min(self.rows - 1, int(y + h - 1) // NAV_TILE)
        return c0, r0, c1, r1

    def block_rect(self, x: float, y: float, w: float, h: float):
        """Mark the nav cells covered by a world-pixel rect as blocked."""
        c0, r0, c1, r1 = self._cell_range(x, y, w, h)
        for r in range(r0, r1 + 1):
            row_off = r * self.cols
            for c in range(c0, c1 + 1):
                self._blocked[row_off + c] = 1

    def unblock_rect(self, x: float, y: float, w: float, h: float):
        """Unblock the nav cells covered by a world-pixel rect.

        Cells whose parent tile is water are kept blocked.
        """
        c0, r0, c1, r1 = self._cell_range(x, y, w, h)
        for r in range(r0, r1 + 1):
            row_off = r * self.cols
            for c in range(c0, c1 + 1):
                if self._tile_map.is_walkable(c // _NAV_SCALE, r // _NAV_SCALE):
                    self._blocked[row_off + c] = 0

    def nearest_walkable(self, col: int, row: int) -> tuple[int, int]:
        """Return the walkable nav cell closest to (col, row)."""
        if self.is_walkable(col, row):
            return col, row
        for r in range(1, 64):
            candidates = [
                (dc * dc + dr * dr, col + dc, row + dr)
                for dc in range(-r, r + 1)
                for dr in range(-r, r + 1)
                if (abs(dc) == r or abs(dr) == r)
                and self.is_walkable(col + dc, row + dr)
            ]
            if candidates:
                _, c, ro = min(candidates)
                return c, ro
        return col, row

    @property
    def flat_bytes(self) -> bytes:
        """Serialised blocked array for passing to subprocess A* workers."""
        return bytes(self._blocked)

