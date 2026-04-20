"""
Map populator — Age of Wars
Reads a map JSON (produced by create_map.py) and writes a fully-populated
scene JSON that the game can load directly.

What is added
-------------
  • One Castle per team, centred on that team's spawn point.
  • Three Pawns per team, arranged in a tight arc on the outward side of
    the castle (i.e. toward the map edge, away from the enemy).

The resource list and zone data from the source map are passed through
unchanged.

Output JSON schema
------------------
{
  "map_file":  str,          # source map filename (basename)
  "seed":      int | null,
  "rows": int, "cols": int, "tile_px": int, "tileset": str,
  "zone_cols": int, "zone_rows": int,
  "tiles":     [[int, ...]],
  "zones":     [{...}],      # from source map
  "buildings": [{"type":str, "x":float, "y":float, "team":str}],
  "units":     [{"type":str, "x":float, "y":float, "team":str}],
  "resources": [{...}],      # from source map
  "spawns":    [{...}]       # from source map
}

Usage
-----
    python map_editor/populate_map.py <map_stem>

    map_stem   path without extension, e.g. "map_editor/maps/map_001"
               or relative/absolute equivalent

    Reads  <stem>.json
    Writes <stem>_scene.json
           <stem>_scene.png   (visual preview)
"""

import json
import math
import os
import sys

# ---------------------------------------------------------------------------
# Placement constants
# ---------------------------------------------------------------------------

# Pawns are placed in an arc on the outward side of the castle.
PAWN_COUNT        = 3
PAWN_RADIUS       = 200.0   # world px from castle centre to each pawn
PAWN_ARC_DEG      = 50.0    # total angular spread of the pawn arc (degrees)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _outward_angle(spawn_x: float, spawn_y: float,
                   map_cx: float, map_cy: float) -> float:
    """Angle (radians) pointing from the map centre toward the spawn."""
    return math.atan2(spawn_y - map_cy, spawn_x - map_cx)


def populate(map_data: dict) -> tuple[list[dict], list[dict]]:
    """
    Return (buildings, units) lists for the scene, derived from the map spawns.

    Each spawn produces:
      - 1 Castle at the spawn centre
      - PAWN_COUNT Pawns fanned out in an arc pointing away from the map centre
    """
    buildings: list[dict] = []
    units:     list[dict] = []

    rows    = map_data["rows"]
    cols    = map_data["cols"]
    tile_px = map_data["tile_px"]
    map_cx  = cols * tile_px / 2.0
    map_cy  = rows * tile_px / 2.0

    for spawn in map_data["spawns"]:
        team = spawn["team"]
        cx   = spawn["x"]
        cy   = spawn["y"]

        buildings.append({
            "type": "Castle",
            "x":    cx,
            "y":    cy,
            "team": team,
        })

        # Arc direction: outward from map centre (safe side, away from enemy)
        base_angle = _outward_angle(cx, cy, map_cx, map_cy)
        half_arc   = math.radians(PAWN_ARC_DEG / 2)

        for i in range(PAWN_COUNT):
            # Lerp from -half_arc to +half_arc across the pawn count
            t     = i / (PAWN_COUNT - 1) if PAWN_COUNT > 1 else 0.0
            angle = base_angle + (t * 2 - 1) * half_arc
            units.append({
                "type": "Pawn",
                "x":    round(cx + math.cos(angle) * PAWN_RADIUS, 1),
                "y":    round(cy + math.sin(angle) * PAWN_RADIUS, 1),
                "team": team,
            })

    return buildings, units


def build_scene(map_data: dict, buildings: list[dict], units: list[dict],
                map_stem: str) -> dict:
    return {
        "map_file":  os.path.basename(map_stem) + ".json",
        "seed":      map_data.get("seed"),
        "rows":      map_data["rows"],
        "cols":      map_data["cols"],
        "tile_px":   map_data["tile_px"],
        "tileset":   map_data["tileset"],
        "zone_cols": map_data["zone_cols"],
        "zone_rows": map_data["zone_rows"],
        "tiles":     map_data["tiles"],
        "zones":     map_data["zones"],
        "buildings": buildings,
        "units":     units,
        "resources": map_data["resources"],
        "spawns":    map_data["spawns"],
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

_TEAM_COLOR = {
    "blue":  (80,  130, 230),
    "black": (30,  30,  60),
}

# Castle display size in world px (from building.py)
_CASTLE_W = 320
_CASTLE_H = 256
_PAWN_R   = 80   # pawn display diameter in world px


def render_preview(scene: dict, out_path: str):
    import os as _os
    _os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    _os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame
    pygame.init()
    pygame.display.set_mode((1, 1))

    SCALE    = 4
    TILE_PX  = scene["tile_px"]
    WPX      = TILE_PX / SCALE   # world px per preview px

    cols = scene["cols"]
    rows = scene["rows"]
    canvas = pygame.Surface((cols * SCALE, rows * SCALE))

    # --- base terrain ---
    for r in range(rows):
        for c in range(cols):
            color = (56, 120, 153) if scene["tiles"][r][c] == 0 else (106, 153, 56)
            pygame.draw.rect(canvas, color, (c * SCALE, r * SCALE, SCALE, SCALE))

    # --- zone tints + borders ---
    for zone in scene["zones"]:
        c0, r0, c1, r1 = zone["col0"], zone["row0"], zone["col1"], zone["row1"]
        zw, zh = (c1 - c0) * SCALE, (r1 - r0) * SCALE
        tint = _ZONE_TINT.get(zone["type"], (106, 153, 56, 60))
        overlay = pygame.Surface((zw, zh), pygame.SRCALPHA)
        overlay.fill(tint)
        canvas.blit(overlay, (c0 * SCALE, r0 * SCALE))
        pygame.draw.rect(canvas, (0, 0, 0), (c0 * SCALE, r0 * SCALE, zw, zh), 1)

    # --- resource dots ---
    for res in scene["resources"]:
        px = int(res["x"] / WPX / TILE_PX * SCALE)   # world px → preview px
        py = int(res["y"] / WPX / TILE_PX * SCALE)
        # simpler: world_px / TILE_PX = tile coord; tile coord * SCALE = preview px
        px = int(res["x"] / TILE_PX * SCALE)
        py = int(res["y"] / TILE_PX * SCALE)
        pygame.draw.circle(canvas, _RES_COLOR.get(res["type"], (255, 255, 255)),
                           (px, py), max(2, SCALE // 2))

    # --- buildings ---
    for b in scene["buildings"]:
        col = _TEAM_COLOR.get(b["team"], (200, 200, 200))
        if b["type"] == "Castle":
            pw = max(2, int(_CASTLE_W / TILE_PX * SCALE))
            ph = max(2, int(_CASTLE_H / TILE_PX * SCALE))
            bx = int(b["x"] / TILE_PX * SCALE) - pw // 2
            by = int(b["y"] / TILE_PX * SCALE) - ph // 2
            pygame.draw.rect(canvas, col, (bx, by, pw, ph))
            pygame.draw.rect(canvas, (255, 255, 255), (bx, by, pw, ph), 1)

    # --- units (pawns) ---
    for u in scene["units"]:
        col = _TEAM_COLOR.get(u["team"], (200, 200, 200))
        px  = int(u["x"] / TILE_PX * SCALE)
        py  = int(u["y"] / TILE_PX * SCALE)
        r   = max(2, int(_PAWN_R / TILE_PX * SCALE))
        pygame.draw.circle(canvas, col, (px, py), r)
        pygame.draw.circle(canvas, (255, 255, 255), (px, py), r, 1)

    pygame.image.save(canvas, out_path)
    pygame.quit()
    print(f"  preview  → {out_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python map_editor/populate_map.py <map_stem>")
        print("  e.g. python map_editor/populate_map.py map_editor/maps/map_001")
        sys.exit(1)

    stem = sys.argv[1]

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isabs(stem):
        stem = os.path.join(base_dir, stem)

    map_path = stem + ".json"
    if not os.path.exists(map_path):
        print(f"Error: map file not found: {map_path}")
        sys.exit(1)

    with open(map_path) as f:
        map_data = json.load(f)

    print(f"Populating {map_path} …")
    buildings, units = populate(map_data)
    scene = build_scene(map_data, buildings, units, stem)

    out_stem = stem + "_scene"
    json_path = out_stem + ".json"
    with open(json_path, "w") as f:
        json.dump(scene, f, separators=(",", ":"))

    counts = {
        "buildings": len(buildings),
        "units":     len(units),
        "resources": len(scene["resources"]),
    }
    print(f"  scene    → {json_path}  {counts}")

    render_preview(scene, out_stem + ".png")
    print("Done.")


if __name__ == "__main__":
    main()
