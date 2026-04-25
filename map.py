import math
import random

TILE_SIZE = 64  # world pixels per tile

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
        self.blocked: set[tuple[int, int]] = set()
        self._tiles_dirty: bool            = True
        self._generate()

    @classmethod
    def from_data(cls, cols: int, rows: int, tiles: list[list[int]]) -> "TileMap":
        """Create a TileMap from a pre-built tile grid (skips procedural generation)."""
        obj = object.__new__(cls)
        obj.cols          = cols
        obj.rows          = rows
        obj.tiles         = [list(row) for row in tiles]
        obj.blocked       = set()
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
        return self.tile_at(col, row) == GRASS and (col, row) not in self.blocked

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

    def block_area(self, world_x: float, world_y: float, half_w: int, half_h: int):
        """Mark a rectangular tile area as unwalkable without changing its visual."""
        cx = int(world_x // TILE_SIZE)
        cy = int(world_y // TILE_SIZE)
        for dr in range(-half_h, half_h + 1):
            for dc in range(-half_w, half_w + 1):
                col, row = cx + dc, cy + dr
                if 0 <= col < self.cols and 0 <= row < self.rows:
                    self.blocked.add((col, row))

    def unblock_area(self, world_x: float, world_y: float, half_w: int, half_h: int):
        """Remove a rectangular tile area from the blocked set."""
        cx = int(world_x // TILE_SIZE)
        cy = int(world_y // TILE_SIZE)
        for dr in range(-half_h, half_h + 1):
            for dc in range(-half_w, half_w + 1):
                self.blocked.discard((cx + dc, cy + dr))

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

