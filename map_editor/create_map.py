"""
Map creation script — Age of Wars
Generates a procedurally zoned 150×250 tile map saved as JSON + PNG preview.

Zone layout
-----------
The interior is divided into a ZONE_COLS × ZONE_ROWS grid.
Two diagonally-opposite corner zones become player starting areas.

Zone types are assigned with a Wave Function Collapse (WFC) algorithm:
  - Collapse starts from both spawn zones and propagates outward.
  - At each step the uncollapsed frontier cell nearest to a spawn (Manhattan
    distance) and with the lowest Shannon entropy is collapsed first.
  - Adjacency rules shape each cell's weight distribution before sampling:
      • Neighbour is a spawn zone  → resource types get a large boost, empty
        gets a penalty (resource-rich areas around the player base).
      • Neighbour has the same type → that type is heavily penalised (avoids
        large homogeneous blobs).
  - After collapsing, the next frontier is the set of uncollapsed cells that
    share an edge with any already-collapsed cell.

Output JSON schema
------------------
{
  "rows": int, "cols": int, "tile_px": int, "tileset": str,
  "seed": int | null,
  "zone_cols": int, "zone_rows": int,
  "tiles":     [[int, ...], ...],   # 0 = water, 1 = grass
  "zones":     [{"zc":int,"zr":int,"col0":int,"row0":int,
                 "col1":int,"row1":int,"type":str}, ...],
  "resources": [{"type":str,"x":float,"y":float,"variant":int}, ...],
  "spawns":    [{"team":str,"x":float,"y":float}, ...]
}

Usage
-----
    python map_editor/create_map.py [output_stem] [seed]

    output_stem defaults to "map_editor/maps/map_001"
    seed        optional integer for reproducible generation
"""

import json
import math
import os
import random
import sys
from math import log

# ---------------------------------------------------------------------------
# Map dimensions
# ---------------------------------------------------------------------------
ROWS         = 150
COLS         = 250
TILE_PX      = 64        # world pixels per tile
WATER_BORDER = 3         # water-tile border thickness

WATER = 0
GRASS = 1

# ---------------------------------------------------------------------------
# Zone layout
# ---------------------------------------------------------------------------
ZONE_COLS = 5
ZONE_ROWS = 3

# Base probability weights for non-spawn zone types
_BASE_W: dict[str, float] = {
    "forest": 35.0,
    "gold":   20.0,
    "meat":   20.0,
    "empty":  25.0,
}
_RESOURCE_TYPES = tuple(_BASE_W.keys())

# WFC adjacency modifiers
_SPAWN_BOOST   = 3.0    # resource-type weight ×  when touching a spawn zone
_SPAWN_PENALTY = 0.25   # empty weight ×           when touching a spawn zone
_SAME_PENALTY  = 0.12   # same-type weight ×       when a neighbour is identical

# ---------------------------------------------------------------------------
# Resource placement parameters keyed by resource type
#   clumps  – (min, max) number of clumps to place
#   size    – (min, max) resources per clump
#   spread  – max radius (world px) of a clump
# ---------------------------------------------------------------------------
_PARAMS = {
    "wood": dict(clumps=(4, 7), size=(3, 5), spread=200),
    "gold": dict(clumps=(2, 4), size=(1, 3), spread=130),
    "meat": dict(clumps=(2, 4), size=(2, 5), spread=160),
}

MIN_RES_DIST       = 80.0   # minimum world-px gap between any two resources
MIN_RES_DIST_WOOD  = 30.0   # trees can crowd much closer together
ZONE_MARGIN   = 128    # world-px inset from zone edges before placing resources


# ---------------------------------------------------------------------------
# Zone geometry helpers
# ---------------------------------------------------------------------------

def _interior() -> tuple[int, int, int, int]:
    """Tile bounds of the non-water interior: (c0, r0, c1, r1)."""
    b = WATER_BORDER
    return b, b, COLS - b, ROWS - b


def zone_tile_bounds(zc: int, zr: int) -> tuple[int, int, int, int]:
    """Tile bounds (col0, row0, col1, row1) for zone (zc, zr)."""
    ic0, ir0, ic1, ir1 = _interior()
    iw, ih = ic1 - ic0, ir1 - ir0
    col0 = ic0 + int(zc       * iw / ZONE_COLS)
    col1 = ic0 + int((zc + 1) * iw / ZONE_COLS) if zc < ZONE_COLS - 1 else ic1
    row0 = ir0 + int(zr       * ih / ZONE_ROWS)
    row1 = ir0 + int((zr + 1) * ih / ZONE_ROWS) if zr < ZONE_ROWS - 1 else ir1
    return col0, row0, col1, row1


def zone_world_center(zc: int, zr: int) -> tuple[float, float]:
    col0, row0, col1, row1 = zone_tile_bounds(zc, zr)
    return (col0 + col1) / 2 * TILE_PX, (row0 + row1) / 2 * TILE_PX


# ---------------------------------------------------------------------------
# Generation steps
# ---------------------------------------------------------------------------

def make_grid() -> list[list[int]]:
    """All-grass interior with a water border."""
    grid = []
    for r in range(ROWS):
        row = []
        for c in range(COLS):
            is_border = (r < WATER_BORDER or r >= ROWS - WATER_BORDER or
                         c < WATER_BORDER or c >= COLS - WATER_BORDER)
            row.append(WATER if is_border else GRASS)
        grid.append(row)
    return grid


def _zone_neighbours(zc: int, zr: int):
    for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nc, nr = zc + dc, zr + dr
        if 0 <= nc < ZONE_COLS and 0 <= nr < ZONE_ROWS:
            yield nc, nr


def _weights_for(cell: tuple[int, int],
                 collapsed: dict[tuple[int, int], str]) -> dict[str, float]:
    """
    Compute WFC-adjusted weights for *cell* given already-collapsed neighbours.

    Rules applied per collapsed neighbour:
      - spawn neighbour  → boost all resource types, penalise empty
      - same-type neighbour → heavily penalise that type (discourages blobs)
    """
    w = dict(_BASE_W)
    for nb in _zone_neighbours(*cell):
        if nb not in collapsed:
            continue
        ntype = collapsed[nb]
        if ntype in ("start_blue", "start_black"):
            w["forest"] *= _SPAWN_BOOST
            w["gold"]   *= _SPAWN_BOOST
            w["meat"]   *= _SPAWN_BOOST
            w["empty"]  *= _SPAWN_PENALTY
        if ntype in _RESOURCE_TYPES:
            w[ntype] = max(0.01, w[ntype] * _SAME_PENALTY)
    return w


def _shannon_entropy(w: dict[str, float]) -> float:
    total = sum(w.values())
    if total <= 0:
        return 0.0
    return -sum((v / total) * log(v / total) for v in w.values() if v > 0)


def assign_zones(rng: random.Random) -> dict[tuple[int, int], str]:
    """
    Wave Function Collapse zone assignment.

    Collapse order:
      1. Both spawn zones are pre-collapsed and seed the frontier.
      2. Each iteration collapses the frontier cell with the smallest
         (spawn_distance, shannon_entropy) score — nearest to a spawn first,
         ties broken by lowest entropy (most constrained).
      3. The newly collapsed cell's uncollapsed neighbours join the frontier.
      4. Any cell not yet reachable is added as a fallback to avoid stalling.
    """
    all_cells = [(zc, zr) for zr in range(ZONE_ROWS) for zc in range(ZONE_COLS)]

    collapsed: dict[tuple[int, int], str] = {
        (0, 0):                         "start_blue",
        (ZONE_COLS - 1, ZONE_ROWS - 1): "start_black",
    }

    spawn_cells = set(collapsed.keys())

    def spawn_dist(cell: tuple[int, int]) -> int:
        return min(abs(cell[0] - sc[0]) + abs(cell[1] - sc[1])
                   for sc in spawn_cells)

    # Seed the frontier with neighbours of the pre-collapsed spawns
    frontier: set[tuple[int, int]] = set()
    for sc in spawn_cells:
        for nb in _zone_neighbours(*sc):
            if nb not in collapsed:
                frontier.add(nb)

    while len(collapsed) < len(all_cells):
        # If the frontier is empty (shouldn't happen on a connected grid, but
        # just in case) pull in every uncollapsed cell.
        if not frontier:
            frontier = {c for c in all_cells if c not in collapsed}

        # Pick the cell to collapse: lowest (spawn_dist, entropy)
        cell = min(
            frontier,
            key=lambda c: (spawn_dist(c), _shannon_entropy(_weights_for(c, collapsed))),
        )
        frontier.discard(cell)

        # Sample from adjusted weights and collapse
        w = _weights_for(cell, collapsed)
        types, vals = zip(*w.items())
        collapsed[cell] = rng.choices(types, vals)[0]

        # Expand frontier
        for nb in _zone_neighbours(*cell):
            if nb not in collapsed:
                frontier.add(nb)

    return collapsed


def place_resources(
    rng: random.Random,
    zones: dict[tuple[int, int], str],
    grid: list[list[int]],
) -> tuple[list[dict], list[dict]]:
    """
    Returns (resources, spawns).
    resources: list of {"type", "x", "y", "variant"}
    spawns:    list of {"team", "x", "y"}
    """
    resources: list[dict] = []
    spawns:    list[dict] = []

    def is_grass(x: float, y: float) -> bool:
        c, r = int(x // TILE_PX), int(y // TILE_PX)
        return 0 <= c < COLS and 0 <= r < ROWS and grid[r][c] == GRASS

    def too_close(x: float, y: float, res_type: str) -> bool:
        min_d = MIN_RES_DIST_WOOD if res_type == "wood" else MIN_RES_DIST
        return any(math.hypot(res["x"] - x, res["y"] - y) < min_d
                   for res in resources)

    def rand_in_zone(zc: int, zr: int) -> tuple[float, float]:
        col0, row0, col1, row1 = zone_tile_bounds(zc, zr)
        return (
            rng.uniform(col0 * TILE_PX + ZONE_MARGIN, col1 * TILE_PX - ZONE_MARGIN),
            rng.uniform(row0 * TILE_PX + ZONE_MARGIN, row1 * TILE_PX - ZONE_MARGIN),
        )

    def try_add(res_type: str, x: float, y: float, variant: int) -> bool:
        if not is_grass(x, y) or too_close(x, y, res_type):
            return False
        resources.append({"type": res_type, "x": round(x, 1), "y": round(y, 1),
                          "variant": variant})
        return True

    def _place_clump(res_type: str, cx: float, cy: float, count: int,
                     spread: float, variant_fn):
        for i in range(count):
            if i == 0:
                x, y = cx, cy
            else:
                angle = rng.uniform(0, 2 * math.pi)
                dist  = rng.uniform(spread * 0.3, spread)
                x = cx + math.cos(angle) * dist
                y = cy + math.sin(angle) * dist
            for _ in range(8):
                if try_add(res_type, x, y, variant_fn()):
                    break
                x += rng.uniform(-40, 40)
                y += rng.uniform(-40, 40)

    def fill_forest_zone(zc: int, zr: int, variant_fn):
        """Spawn 3-5 tree clusters arranged in a line to create sprawling forests."""
        num_clusters  = rng.randint(3, 5)
        cluster_spread = 170   # tree scatter radius around each cluster center
        cluster_step   = rng.uniform(150, 220)  # world-px spacing between clusters

        # Pick a line origin inside the zone and a random direction
        ox, oy    = rand_in_zone(zc, zr)
        direction = rng.uniform(0, 2 * math.pi)
        dx, dy    = math.cos(direction), math.sin(direction)

        # Offset so the line is centred on the origin point
        half = (num_clusters - 1) / 2.0
        for i in range(num_clusters):
            t  = (i - half) * cluster_step
            cx = ox + dx * t
            cy = oy + dy * t
            count = rng.randint(10, 20)
            _place_clump("wood", cx, cy, count, cluster_spread, variant_fn)

    def fill_zone(zc: int, zr: int, res_type: str, variant_fn):
        p = _PARAMS[res_type]
        num_clumps = rng.randint(*p["clumps"])
        spread     = p["spread"]

        for _ in range(num_clumps):
            cx, cy = rand_in_zone(zc, zr)
            count  = rng.randint(*p["size"])
            _place_clump(res_type, cx, cy, count, spread, variant_fn)

    for (zc, zr), ztype in zones.items():
        if ztype == "start_blue":
            cx, cy = zone_world_center(zc, zr)
            spawns.append({"team": "blue",  "x": round(cx, 1), "y": round(cy, 1)})

        elif ztype == "start_black":
            cx, cy = zone_world_center(zc, zr)
            spawns.append({"team": "black", "x": round(cx, 1), "y": round(cy, 1)})

        elif ztype == "forest":
            fill_forest_zone(zc, zr, lambda: rng.randint(0, 3))

        elif ztype == "gold":
            fill_zone(zc, zr, "gold", lambda: rng.randint(1, 6))

        elif ztype == "meat":
            fill_zone(zc, zr, "meat", lambda: 0)

        # "empty" → nothing to place

    return resources, spawns


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def build_output(
    grid: list[list[int]],
    zones: dict[tuple[int, int], str],
    resources: list[dict],
    spawns: list[dict],
    seed,
) -> dict:
    zone_list = []
    for (zc, zr), ztype in sorted(zones.items()):
        col0, row0, col1, row1 = zone_tile_bounds(zc, zr)
        zone_list.append({
            "zc": zc, "zr": zr,
            "col0": col0, "row0": row0,
            "col1": col1, "row1": row1,
            "type": ztype,
        })
    return {
        "rows":      ROWS,
        "cols":      COLS,
        "tile_px":   TILE_PX,
        "tileset":   "Tilemap_color1",
        "seed":      seed,
        "zone_cols": ZONE_COLS,
        "zone_rows": ZONE_ROWS,
        "tiles":     grid,
        "zones":     zone_list,
        "resources": resources,
        "spawns":    spawns,
    }


# ---------------------------------------------------------------------------
# Preview renderer
# ---------------------------------------------------------------------------

_ZONE_TINT = {
    "start_blue":  (80,  120, 220, 140),
    "start_black": (40,  40,  70,  140),
    "forest":      (30,  110, 30,  120),
    "gold":        (210, 175, 30,  120),
    "meat":        (220, 190, 160, 120),
    "empty":       (106, 153, 56,  60),
}

_RES_COLOR = {
    "wood": (20,  80,  20),
    "gold": (240, 200, 30),
    "meat": (220, 220, 220),
}

_SPAWN_COLOR = {
    "blue":  (80,  120, 220),
    "black": (30,  30,  60),
}


def render_preview(
    grid: list[list[int]],
    zones: dict[tuple[int, int], str],
    resources: list[dict],
    spawns: list[dict],
    out_path: str,
):
    import os as _os
    _os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    _os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame
    pygame.init()
    pygame.display.set_mode((1, 1))

    SCALE = 4
    canvas = pygame.Surface((COLS * SCALE, ROWS * SCALE))

    # --- base terrain ---
    for r in range(ROWS):
        for c in range(COLS):
            color = (56, 120, 153) if grid[r][c] == WATER else (106, 153, 56)
            canvas.set_at((c * SCALE, r * SCALE), color)
            # fill the SCALE×SCALE block
            pygame.draw.rect(canvas, color, (c * SCALE, r * SCALE, SCALE, SCALE))

    # --- zone tints + borders ---
    for (zc, zr), ztype in zones.items():
        col0, row0, col1, row1 = zone_tile_bounds(zc, zr)
        zw = (col1 - col0) * SCALE
        zh = (row1 - row0) * SCALE
        tint = _ZONE_TINT.get(ztype, (106, 153, 56, 80))
        overlay = pygame.Surface((zw, zh), pygame.SRCALPHA)
        overlay.fill(tint)
        canvas.blit(overlay, (col0 * SCALE, row0 * SCALE))
        pygame.draw.rect(canvas, (0, 0, 0),
                         (col0 * SCALE, row0 * SCALE, zw, zh), 1)

    # --- resource dots ---
    for res in resources:
        px = int(res["x"] / TILE_PX * SCALE)
        py = int(res["y"] / TILE_PX * SCALE)
        pygame.draw.circle(canvas, _RES_COLOR.get(res["type"], (255, 255, 255)),
                           (px, py), max(2, SCALE // 2))

    # --- spawn markers ---
    for sp in spawns:
        px = int(sp["x"] / TILE_PX * SCALE)
        py = int(sp["y"] / TILE_PX * SCALE)
        col = _SPAWN_COLOR.get(sp["team"], (200, 200, 200))
        pygame.draw.circle(canvas, col, (px, py), SCALE * 4, 2)
        pygame.draw.line(canvas, col, (px - SCALE * 4, py), (px + SCALE * 4, py), 1)
        pygame.draw.line(canvas, col, (px, py - SCALE * 4), (px, py + SCALE * 4), 1)

    pygame.image.save(canvas, out_path)
    pygame.quit()
    print(f"  preview  → {out_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    stem = sys.argv[1] if len(sys.argv) > 1 else "map_editor/maps/map_001"
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else None

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isabs(stem):
        stem = os.path.join(base_dir, stem)
    os.makedirs(os.path.dirname(stem), exist_ok=True)

    actual_seed = seed if seed is not None else random.randrange(2**32)
    rng = random.Random(actual_seed)

    print(f"Generating {ROWS}×{COLS} map  seed={actual_seed} …")

    grid               = make_grid()
    zones              = assign_zones(rng)
    resources, spawns  = place_resources(rng, zones, grid)
    data               = build_output(grid, zones, resources, spawns, actual_seed)

    json_path = stem + ".json"
    with open(json_path, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"  map data → {json_path}"
          f"  ({len(resources)} resources, {len(spawns)} spawns)")

    render_preview(grid, zones, resources, spawns, stem + ".png")
    print("Done.")


if __name__ == "__main__":
    main()
