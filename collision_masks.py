"""
Pre-compute pixel-perfect collision masks for every game entity.

For each sprite the script:
  1. Loads the image from the Tiny Swords zip (via assets.load_image).
  2. Picks the first frame (idle pose) for animated sheets.
  3. Scales it to the entity's display dimensions so the mask is in world units.
  4. Zeroes out the top 33% of pixels — units can pass behind tall sprites.
  5. For facing-aware entities (units, sheep) also stores a horizontally
     mirrored mask.

The result is serialised to ``collision_masks.json`` at the repo root.
Re-run only when asset shapes change. The runtime call ``ensure_built()`` is
idempotent and used by ``server_main.py`` so the JSON is auto-generated on
first run.
"""
from __future__ import annotations
import argparse
import base64
import json
import os
import sys

# Headless SDL — must be set before pygame is imported.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assets  # noqa: E402


OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "collision_masks.json")
TOP_TRANSPARENT_FRACTION = 1.0 / 3.0   # top third of every sprite is non-blocking

# ---------------------------------------------------------------------------
# Sprite catalogue
# Mask shapes are team-invariant, so we only ever load the "Blue" variant.
# Each spec: (asset_path, native_frame_w, display_w, display_h)
# native_frame_w == 0 means the file is a single image (no sheet slicing).
# ---------------------------------------------------------------------------

_BUILDING_SPECS = {
    "building/archery":   ("assets/Buildings/Blue Buildings/Archery.png",   0, 192, 256),
    "building/barracks":  ("assets/Buildings/Blue Buildings/Barracks.png",  0, 192, 256),
    "building/castle":    ("assets/Buildings/Blue Buildings/Castle.png",    0, 320, 256),
    "building/house1":    ("assets/Buildings/Blue Buildings/House1.png",    0, 128, 128),
    "building/house2":    ("assets/Buildings/Blue Buildings/House2.png",    0, 128, 128),
    "building/house3":    ("assets/Buildings/Blue Buildings/House3.png",    0, 128, 128),
    "building/tower":     ("assets/Buildings/Blue Buildings/Tower.png",     0, 128, 256),
    "building/monastery": ("assets/Buildings/Blue Buildings/Monastery.png", 0, 192, 320),
}

# Facing-aware: we generate a mirrored mask too.
_UNIT_SPECS = {
    "unit/pawn":    ("assets/Units/Blue Units/Pawn/Pawn_Idle.png",       192, 80,  80),
    "unit/archer":  ("assets/Units/Blue Units/Archer/Archer_Idle.png",   192, 96,  96),
    "unit/warrior": ("assets/Units/Blue Units/Warrior/Warrior_Idle.png", 192, 128, 128),
    "unit/lancer":  ("assets/Units/Blue Units/Lancer/Lancer_Idle.png",   320, 128, 128),
    "unit/monk":    ("assets/Units/Blue Units/Monk/Idle.png",            192, 128, 128),
}

# Gold: 6 variants. Wood: 4 variants. Sheep: 1, facing-aware.
_RESOURCE_SPECS = {
    **{f"resource/gold/{n}": (f"assets/Terrain/Resources/Gold/Gold Stones/Gold Stone {n}_Highlight.png", 128, 96, 96)
       for n in range(1, 7)},
    **{f"resource/wood/{n}": (f"assets/Terrain/Resources/Wood/Trees/Tree{n}.png", 192, 112, 112)
       for n in range(1, 5)},
    "resource/sheep": ("assets/Terrain/Resources/Meat/Sheep/Sheep_Idle.png", 128, 80, 80),
}

_FACING_AWARE = set(_UNIT_SPECS) | {"resource/sheep"}


# ---------------------------------------------------------------------------
# Mask construction
# ---------------------------------------------------------------------------

def _first_frame(surf: pygame.Surface, frame_w: int) -> pygame.Surface:
    """Return the first frame of a horizontal sprite sheet, or the surface itself."""
    if frame_w == 0 or surf.get_width() == frame_w:
        return surf
    return surf.subsurface(pygame.Rect(0, 0, frame_w, surf.get_height())).copy()


def _build_mask(asset_path: str, frame_w: int, dw: int, dh: int) -> pygame.mask.Mask:
    surf = assets.load_image(asset_path).convert_alpha()
    frame = _first_frame(surf, frame_w)
    scaled = pygame.transform.smoothscale(frame, (dw, dh))
    mask = pygame.mask.from_surface(scaled, threshold=0)
    # Zero out the top 33% so the upper body never blocks.
    cutoff = int(dh * TOP_TRANSPARENT_FRACTION)
    for y in range(cutoff):
        for x in range(dw):
            if mask.get_at((x, y)):
                mask.set_at((x, y), 0)
    return mask


def _mask_to_bits_b64(mask: pygame.mask.Mask) -> str:
    """Pack a Mask into a row-major MSB-first bit string, then base64-encode."""
    w, h = mask.get_size()
    total = w * h
    out = bytearray((total + 7) // 8)
    for y in range(h):
        for x in range(w):
            if mask.get_at((x, y)):
                idx = y * w + x
                out[idx // 8] |= 0x80 >> (idx % 8)
    return base64.b64encode(bytes(out)).decode("ascii")


def _mirror_mask(mask: pygame.mask.Mask) -> pygame.mask.Mask:
    w, h = mask.get_size()
    out = pygame.mask.Mask((w, h))
    for y in range(h):
        for x in range(w):
            if mask.get_at((x, y)):
                out.set_at((w - 1 - x, y), 1)
    return out


# ---------------------------------------------------------------------------
# Build pipeline
# ---------------------------------------------------------------------------

def build(output_path: str = OUTPUT_PATH) -> None:
    # Headless pygame must have a video sub-system initialised even with the
    # dummy driver so that ``convert_alpha`` / ``smoothscale`` work.
    pygame.display.init()
    pygame.display.set_mode((1, 1))

    entries: dict[str, dict] = {}
    catalogue = {**_BUILDING_SPECS, **_UNIT_SPECS, **_RESOURCE_SPECS}
    for key, (path, frame_w, dw, dh) in catalogue.items():
        mask = _build_mask(path, frame_w, dw, dh)
        rec  = {"w": dw, "h": dh, "bits": _mask_to_bits_b64(mask)}
        if key in _FACING_AWARE:
            rec["bits_mirror"] = _mask_to_bits_b64(_mirror_mask(mask))
        entries[key] = rec
        print(f"[masks] {key}: {dw}x{dh} ({len(rec['bits'])} b64 bytes)")

    with open(output_path, "w") as f:
        json.dump({"masks": entries}, f, separators=(",", ":"))
    print(f"[masks] Wrote {output_path}")


def ensure_built(output_path: str = OUTPUT_PATH) -> None:
    """Build the JSON if it isn't already present."""
    if not os.path.isfile(output_path):
        build(output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build collision masks JSON.")
    parser.add_argument("--rebuild", action="store_true",
                        help="Force rebuild even if collision_masks.json already exists.")
    args = parser.parse_args()
    if args.rebuild and os.path.isfile(OUTPUT_PATH):
        os.remove(OUTPUT_PATH)
    ensure_built()
