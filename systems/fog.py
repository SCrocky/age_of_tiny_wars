UNEXPLORED = 0
EXPLORED   = 1
VISIBLE    = 2


class FogOfWar:
    """Per-tile visibility state for one team."""

    def __init__(self, rows: int, cols: int):
        self.rows = rows
        self.cols = cols
        self._state = bytearray(rows * cols)  # flat array, row-major
        self._visible: set[int] = set()       # indices of currently VISIBLE tiles

    def update(self, friendly_entities, tile_size: float):
        """Recompute visibility from all living friendly entities."""
        rows, cols = self.rows, self.cols
        state = self._state
        visible = self._visible

        # Decay VISIBLE → EXPLORED using tracked indices (avoids full O(rows*cols) scan)
        for i in visible:
            state[i] = EXPLORED
        visible.clear()

        # Reveal tiles around each friendly entity
        for entity in friendly_entities:
            if not getattr(entity, "alive", True):
                continue
            radius = getattr(entity, "VISION_RADIUS", 5)
            cx = int(entity.x / tile_size)
            cy = int(entity.y / tile_size)
            r2 = radius * radius
            c0 = max(0, cx - radius)
            c1 = min(cols - 1, cx + radius)
            r0 = max(0, cy - radius)
            r1 = min(rows - 1, cy + radius)
            for row in range(r0, r1 + 1):
                dr = row - cy
                for col in range(c0, c1 + 1):
                    dc = col - cx
                    if dr * dr + dc * dc <= r2:
                        idx = row * cols + col
                        state[idx] = VISIBLE
                        visible.add(idx)

    def tile_state(self, col: int, row: int) -> int:
        if col < 0 or col >= self.cols or row < 0 or row >= self.rows:
            return UNEXPLORED
        return self._state[row * self.cols + col]

    def is_visible(self, world_x: float, world_y: float, tile_size: float) -> bool:
        return self.tile_state(int(world_x / tile_size), int(world_y / tile_size)) == VISIBLE

    def is_explored(self, world_x: float, world_y: float, tile_size: float) -> bool:
        return self.tile_state(int(world_x / tile_size), int(world_y / tile_size)) >= EXPLORED
