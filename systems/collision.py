"""
Pixel-perfect runtime collision using pre-computed pygame masks.

Masks are generated once by ``collision_masks.py`` and loaded here. They are
already shrunk so the top 33% of every sprite is non-blocking (lets short
units walk visually behind tall buildings).

Hot-path strategy:
    * Every entity is ``register()``-ed once on creation; mask refs and AABB
      half-sizes are cached directly on the instance under ``_col_*`` attrs.
      The hot loop is pure attribute reads — no ``hasattr``, no dict lookups.
    * Static obstacles (buildings, blueprints, trees, gold) live in a
      ``StaticGrid`` keyed on world tile bins. The grid is built once at game
      start and maintained on placement / destruction.
    * Dynamic entities (units, pawns, sheep) are passed in as a small list;
      they're few enough that linear iteration beats grid maintenance.
    * Each pair-wise check starts with an AABB rejection on sprite half-sizes;
      only candidates that pass run ``pygame.mask.overlap``.

Public surface:
    init()                                 – load masks (idempotent)
    register(entity)                       – attach _col_* attrs (call once)
    StaticGrid()                           – spatial hash for non-moving entities
    overlaps(a, b)                         – ad-hoc pair check
    any_overlap(entity, grid, dynamics,
                skip_wood)                 – True if entity collides with anything
    resolve_move(e, ox, oy, grid, dynamics,
                 skip_wood)                – axis-slide back from collisions

Depleted resources must be removed from the grid by the caller — there is no
``depleted`` check in the hot path.
"""
from __future__ import annotations
import base64
import json
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame  # noqa: E402

from map import TILE_SIZE, NAV_TILE  # noqa: E402

_JSON_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "collision_masks.json")

# key -> (mask, mirror_or_None, half_w, half_h)
_masks: dict[str, tuple[pygame.mask.Mask, pygame.mask.Mask | None, float, float]] = {}
_ready: bool = False


# ---------------------------------------------------------------------------
# Init / load
# ---------------------------------------------------------------------------

def init() -> None:
    global _ready
    if _ready:
        return
    if not os.path.isfile(_JSON_PATH):
        raise FileNotFoundError(
            f"collision_masks.json not found at {_JSON_PATH}. "
            "Run `python collision_masks.py` to build it."
        )
    with open(_JSON_PATH) as f:
        data = json.load(f)
    for key, rec in data["masks"].items():
        w, h = rec["w"], rec["h"]
        mask = _bits_to_mask(rec["bits"], w, h)
        mirror = _bits_to_mask(rec["bits_mirror"], w, h) if "bits_mirror" in rec else None
        _masks[key] = (mask, mirror, w * 0.5, h * 0.5)
    _ready = True


def _bits_to_mask(bits_b64: str, w: int, h: int) -> pygame.mask.Mask:
    raw = base64.b64decode(bits_b64)
    mask = pygame.mask.Mask((w, h))
    total = w * h
    for idx in range(total):
        if raw[idx >> 3] & (0x80 >> (idx & 7)):
            mask.set_at((idx % w, idx // w), 1)
    return mask


# ---------------------------------------------------------------------------
# Entity → mask lookup
# ---------------------------------------------------------------------------

# Class-name → mask key. Lancer/Archer/etc. share a single mask each.
_UNIT_KEY = {
    "Pawn":     "unit/pawn",
    "Archer":   "unit/archer",
    "Warrior":  "unit/warrior",
    "Lancer":   "unit/lancer",
    "Monk":     "unit/monk",
    "MeatNode": "resource/sheep",
}

# Circle radii for dynamic units — used instead of pixel masks for unit-vs-unit
# collision. Intentionally smaller than the sprite half-size to prevent sticking.
# Lancer radius ignores the lance (body width ~100 px on a 128-px sprite).
_UNIT_RADII: dict[str, float] = {
    "Pawn":    24.0,   # sprite 80×80,   half=40
    "Archer":  29.0,   # sprite 96×96,   half=48
    "Warrior": 38.0,   # sprite 128×128, half=64
    "Lancer":  30.0,   # sprite 128×128, half=64 — lance excluded
    "Monk":    38.0,   # sprite 128×128, half=64
}


def _resolve_key(entity) -> str | None:
    """Slow path: figure out which mask this entity wants. Called once per entity."""
    # Blueprint → underlying building
    inner = getattr(entity, "_building", None)
    if inner is not None:
        return _resolve_key(inner)

    sk = getattr(entity, "sprite_key", None) or ""
    if sk.startswith("building/"):
        parts = sk.split("/")
        return f"building/{parts[1]}"
    if sk.startswith("resource/"):
        return sk  # resource/gold/N | resource/wood/N

    return _UNIT_KEY.get(type(entity).__name__)


def register(entity) -> None:
    """Cache mask refs and AABB half-sizes on the entity. Call once per entity."""
    key = _resolve_key(entity)
    rec = _masks.get(key) if key is not None else None
    # _facing_right is set by Units in their own __init__; default for everything
    # else (buildings, resources, blueprints) so the hot loop can do direct reads.
    if not hasattr(entity, "_facing_right"):
        entity._facing_right = True
    entity._col_radius = _UNIT_RADII.get(type(entity).__name__)
    if rec is None:
        entity._col_mask = None
        entity._col_mirror = None
        entity._col_hw = 0.0
        entity._col_hh = 0.0
        entity._col_is_wood = False
        return
    mask, mirror, hw, hh = rec
    entity._col_mask = mask
    entity._col_mirror = mirror
    entity._col_hw = hw
    entity._col_hh = hh
    entity._col_is_wood = key is not None and key.startswith("resource/wood")


# ---------------------------------------------------------------------------
# Spatial grid for non-moving entities
# ---------------------------------------------------------------------------

class StaticGrid:
    """Spatial hash for entities that don't move (buildings, trees, gold piles)."""

    CELL = 320  # ≥ widest sprite, so an entity occupies exactly one cell

    def __init__(self):
        self.buckets: dict[tuple[int, int], list] = {}
        self._cell_of: dict[int, tuple[int, int]] = {}

    def add(self, entity) -> None:
        if entity._col_mask is None:
            return
        key = (int(entity.x // self.CELL), int(entity.y // self.CELL))
        bucket = self.buckets.get(key)
        if bucket is None:
            bucket = []
            self.buckets[key] = bucket
        bucket.append(entity)
        self._cell_of[id(entity)] = key

    def remove(self, entity) -> None:
        key = self._cell_of.pop(id(entity), None)
        if key is None:
            return
        bucket = self.buckets.get(key)
        if bucket is None:
            return
        try:
            bucket.remove(entity)
        except ValueError:
            pass
        if not bucket:
            del self.buckets[key]


# ---------------------------------------------------------------------------
# Overlap tests — inlined hot loop
# ---------------------------------------------------------------------------

def overlaps(a, b) -> bool:
    """Ad-hoc pair check. Both entities must have been ``register()``-ed."""
    ma_base = a._col_mask
    mb_base = b._col_mask
    if ma_base is None or mb_base is None:
        return False
    a_hw, a_hh = a._col_hw, a._col_hh
    b_hw, b_hh = b._col_hw, b._col_hh
    ax_c, ay_c = a.x, a.y
    bx_c, by_c = b.x, b.y
    dx = bx_c - ax_c
    if dx < 0: dx = -dx
    if dx >= a_hw + b_hw: return False
    dy = by_c - ay_c
    if dy < 0: dy = -dy
    if dy >= a_hh + b_hh: return False
    a_mirror = a._col_mirror
    mask_a = a_mirror if (a_mirror is not None and not a._facing_right) else ma_base
    b_mirror = b._col_mirror
    mask_b = b_mirror if (b_mirror is not None and not b._facing_right) else mb_base
    return mask_a.overlap(
        mask_b,
        (int((bx_c - b_hw) - (ax_c - a_hw)),
         int((by_c - b_hh) - (ay_c - a_hh))),
    ) is not None


def any_overlap(entity, grid: StaticGrid, dynamics=(), skip_wood: bool = False) -> bool:
    """
    True if ``entity`` collides with any static (grid) or dynamic neighbor.

    ``skip_wood=True`` skips WoodNode entities — used so a pawn in GATHER mode
    can walk into the tree it's harvesting. Depleted resources must already
    have been removed from the grid by the caller.
    """
    ma_base = entity._col_mask
    if ma_base is None:
        return False
    a_hw = entity._col_hw
    a_hh = entity._col_hh
    ax_c = entity.x
    ay_c = entity.y
    ax_topleft = ax_c - a_hw
    ay_topleft = ay_c - a_hh
    a_mirror = entity._col_mirror
    if a_mirror is not None and not entity._facing_right:
        mask_a = a_mirror
    else:
        mask_a = ma_base

    # ---- 3x3 cell neighborhood in the static grid ----
    cs = StaticGrid.CELL
    cx = int(ax_c // cs)
    cy = int(ay_c // cs)
    buckets = grid.buckets
    for dcy in (-1, 0, 1):
        for dcx in (-1, 0, 1):
            bucket = buckets.get((cx + dcx, cy + dcy))
            if bucket is None:
                continue
            for other in bucket:
                if skip_wood and other._col_is_wood:
                    continue
                mb_base = other._col_mask
                if mb_base is None:
                    continue
                b_hw = other._col_hw
                b_hh = other._col_hh
                ox_c = other.x
                oy_c = other.y
                dx = ox_c - ax_c
                if dx < 0: dx = -dx
                if dx >= a_hw + b_hw: continue
                dy = oy_c - ay_c
                if dy < 0: dy = -dy
                if dy >= a_hh + b_hh: continue
                b_mirror = other._col_mirror
                if b_mirror is not None and not other._facing_right:
                    mask_b = b_mirror
                else:
                    mask_b = mb_base
                if mask_a.overlap(
                    mask_b,
                    (int((ox_c - b_hw) - ax_topleft),
                     int((oy_c - b_hh) - ay_topleft)),
                ) is not None:
                    return True

    # ---- Dynamic entities (small list, linear scan) ----
    # Dynamics are units, pawns, sheep — none are WoodNode, so skip_wood is
    # irrelevant here. Depleted sheep are filtered out by the caller before
    # building this list.
    #
    # Unit-vs-unit: circle check (avoids pixel-mask stickiness).
    # Any other pairing: fall back to mask.
    a_radius = entity._col_radius
    for other in dynamics:
        if other is entity:
            continue
        ox_c = other.x
        oy_c = other.y
        b_radius = other._col_radius
        if a_radius is not None and b_radius is not None:
            rdx = ox_c - ax_c
            rdy = oy_c - ay_c
            r_sum = a_radius + b_radius
            if rdx * rdx + rdy * rdy < r_sum * r_sum:
                return True
            continue
        mb_base = other._col_mask
        if mb_base is None:
            continue
        b_hw = other._col_hw
        b_hh = other._col_hh
        dx = ox_c - ax_c
        if dx < 0: dx = -dx
        if dx >= a_hw + b_hw: continue
        dy = oy_c - ay_c
        if dy < 0: dy = -dy
        if dy >= a_hh + b_hh: continue
        b_mirror = other._col_mirror
        if b_mirror is not None and not other._facing_right:
            mask_b = b_mirror
        else:
            mask_b = mb_base
        if mask_a.overlap(
            mask_b,
            (int((ox_c - b_hw) - ax_topleft),
             int((oy_c - b_hh) - ay_topleft)),
        ) is not None:
            return True
    return False


# ---------------------------------------------------------------------------
# Movement resolution — axis slide
# ---------------------------------------------------------------------------

# Tiny push applied every tick so a unit doesn't glue to a surface.
_BUMP_PX:             float = 2.0
# Extra gap kept between the unit's collision radius and the building surface.
_AVOIDANCE_CLEARANCE: float = 4.0
# Unit-vs-unit separation parameters.
_SEP_FRACTION:        float = 0.5   # fraction of overlap corrected per tick
_HEAD_ON_THRESH:      float = -0.7  # alignment dot below this → CW bypass
_AVOID_RADIUS_MULT:   float = 2.5   # look-ahead zone as multiple of r_sum
_AVOID_STRENGTH:      float = 5.0   # max pre-emptive lateral push (px/tick)


def _find_static_blocker(entity, grid: StaticGrid, skip_wood: bool):
    """First static-grid neighbor whose AABB overlaps entity (no mask check).

    Used only by the resolve_move unstick path; an AABB-near blocker is a
    fine direction reference and is cheaper than a full mask lookup.
    """
    if entity._col_mask is None:
        return None
    a_hw = entity._col_hw
    a_hh = entity._col_hh
    ax_c = entity.x
    ay_c = entity.y
    cs = StaticGrid.CELL
    cx = int(ax_c // cs)
    cy = int(ay_c // cs)
    buckets = grid.buckets
    for dcy in (-1, 0, 1):
        for dcx in (-1, 0, 1):
            bucket = buckets.get((cx + dcx, cy + dcy))
            if bucket is None:
                continue
            for other in bucket:
                if skip_wood and other._col_is_wood:
                    continue
                if other._col_mask is None:
                    continue
                dx = other.x - ax_c
                if dx < 0: dx = -dx
                if dx >= a_hw + other._col_hw: continue
                dy = other.y - ay_c
                if dy < 0: dy = -dy
                if dy >= a_hh + other._col_hh: continue
                return other
    return None


def resolve_move(entity, old_x: float, old_y: float,
                 grid: StaticGrid, dynamics=(), skip_wood: bool = False) -> None:
    """
    Slide-block ``entity`` against the world.

    Axis-slide first (X-only, then Y-only).  When fully blocked by a static
    obstacle, steer tangentially around it: decompose the intended movement
    into a component along the blocker's surface and one into it, keep only
    the tangential part, and push outward enough to maintain clearance so the
    unit doesn't immediately re-collide on the next tick.
    """
    new_x, new_y = entity.x, entity.y
    if not any_overlap(entity, grid, dynamics, skip_wood):
        return
    entity.x, entity.y = new_x, old_y
    if not any_overlap(entity, grid, dynamics, skip_wood):
        return
    entity.x, entity.y = old_x, new_y
    if not any_overlap(entity, grid, dynamics, skip_wood):
        return

    # Fully blocked — find the static obstacle we're stuck against.
    entity.x, entity.y = new_x, new_y
    blocker = _find_static_blocker(entity, grid, skip_wood)
    entity.x, entity.y = old_x, old_y
    if blocker is None:
        return

    # Surface normal: direction from the nearest point on the blocker's AABB
    # to the unit centre.  This is the outward normal of the surface we hit.
    bx, by   = blocker.x, blocker.y
    bhw, bhh = blocker._col_hw, blocker._col_hh
    px = max(bx - bhw, min(old_x, bx + bhw))
    py = max(by - bhh, min(old_y, by + bhh))
    nx, ny = old_x - px, old_y - py
    nd = (nx * nx + ny * ny) ** 0.5
    if nd < 1e-6:                   # unit centre exactly on AABB edge / inside
        nx = (old_x - bx) if (old_x != bx) else 1.0
        ny = old_y - by
        nd = (nx * nx + ny * ny) ** 0.5
        if nd < 1e-6:               # also coincident on Y — pick +X arbitrarily
            nx, ny, nd = 1.0, 0.0, 1.0
    nx /= nd
    ny /= nd

    # How far to push outward so the unit's collision radius clears the surface.
    col_r  = entity._col_radius or entity._col_hw
    push   = max(_BUMP_PX, col_r + _AVOIDANCE_CLEARANCE - nd)

    # Decompose intended movement into tangential component (along surface).
    move_x = new_x - old_x
    move_y = new_y - old_y
    move_len = (move_x * move_x + move_y * move_y) ** 0.5
    if move_len < 1e-6:
        entity.x = old_x + nx * push
        entity.y = old_y + ny * push
        return

    # Pick the tangent perpendicular that best matches the desired direction.
    tx, ty = -ny, nx
    if move_x * tx + move_y * ty < 0:
        tx, ty = ny, -nx

    tang_dot = move_x * tx + move_y * ty
    if tang_dot < 1e-6:
        # Moving straight into the surface — only push away.
        entity.x = old_x + nx * push
        entity.y = old_y + ny * push
        return

    entity.x = old_x + tx * move_len + nx * push
    entity.y = old_y + ty * move_len + ny * push

    # Safety: if tangential position still overlaps (e.g. concave corner),
    # fall back to a pure outward push from the old position.
    if any_overlap(entity, grid, dynamics, skip_wood):
        entity.x = old_x + nx * push
        entity.y = old_y + ny * push


# ---------------------------------------------------------------------------
# Unit-vs-unit separation
# ---------------------------------------------------------------------------

def _unit_vel_dir(entity) -> tuple[float, float]:
    """Return a unit vector for where ``entity`` is currently trying to travel."""
    path = getattr(entity, "path", None)
    if path:
        col, row = path[0]
        dx = col * NAV_TILE + NAV_TILE * 0.5 - entity.x
        dy = row * NAV_TILE + NAV_TILE * 0.5 - entity.y
        d = (dx * dx + dy * dy) ** 0.5
        if d > 1e-6:
            return dx / d, dy / d
    at = getattr(entity, "_approach_target", None)
    if at is not None:
        tx, ty, _ = at
        dx, dy = tx - entity.x, ty - entity.y
        d = (dx * dx + dy * dy) ** 0.5
        if d > 1e-6:
            return dx / d, dy / d
    # Combat chase with no queued path/approach: aim at attack target.
    tgt = getattr(entity, "attack_target", None)
    if tgt is not None and getattr(tgt, "alive", True):
        get_point = getattr(tgt, "sprite_closest_point", None) \
                 or getattr(tgt, "closest_point", None)
        if get_point is not None:
            tx, ty = get_point(entity.x, entity.y)
            dx, dy = tx - entity.x, ty - entity.y
            d = (dx * dx + dy * dy) ** 0.5
            if d > 1e-6:
                return dx / d, dy / d
    return 0.0, 0.0


def separate_units(dynamics) -> None:
    """
    Resolve unit-vs-unit overlaps with alignment-aware force vectors.

    Three regimes keyed on the dot-product of both units' intended directions:

      alignment > 0   (co-moving)   → separation rotated toward travel
                                      perpendicular so units spread sideways
                                      without losing forward speed.
      alignment ≈ 0   (crossing)    → plain radial separation.
      alignment < -0.7 (head-on)    → screen-space clockwise perpendicular
                                      applied to each unit's own velocity so
                                      they orbit past each other.

    Forces for every overlapping pair are accumulated first and applied
    simultaneously, so the outcome is order-independent and N-way pileups
    resolve without bias.  Stationary units receive forces just like moving
    ones — they are pushable.
    """
    n = len(dynamics)
    if n < 2:
        return

    force_x = [0.0] * n
    force_y = [0.0] * n

    for i in range(n):
        a  = dynamics[i]
        ra = a._col_radius
        if ra is None or not getattr(a, "alive", True):
            continue
        avx, avy = _unit_vel_dir(a)

        for j in range(i + 1, n):
            b  = dynamics[j]
            rb = b._col_radius
            if rb is None or not getattr(b, "alive", True):
                continue

            dx = b.x - a.x
            dy = b.y - a.y
            dist2 = dx * dx + dy * dy
            r_sum = ra + rb
            r_avoid = r_sum * _AVOID_RADIUS_MULT

            if dist2 >= r_avoid * r_avoid:
                continue  # outside both overlap and avoidance zones

            dist = dist2 ** 0.5 or 1e-6
            sx = dx / dist
            sy = dy / dist
            bvx, bvy = _unit_vel_dir(b)

            if dist2 < r_sum * r_sum:
                # ---- Overlapping: reactive separation ----
                overlap = (r_sum - dist) * _SEP_FRACTION

                # Allied push-through: a moving unit shoves a stationary ally
                # out of its path instead of the two blocking each other.
                # "Stationary" = no active path, attack target, or approach.
                a_moving = avx != 0.0 or avy != 0.0
                b_moving = bvx != 0.0 or bvy != 0.0
                pushed = False
                a_team = getattr(a, "team", None)
                b_team = getattr(b, "team", None)
                # Allow push-through between same-team allies OR when either
                # unit is neutral (e.g. sheep): moving unit shoves it aside.
                allow_push = (a_team == b_team and a_team is not None) \
                          or a_team is None or b_team is None
                if allow_push:
                    if a_moving and not b_moving:
                        # Moving A pushes stationary B aside; A barely slows.
                        force_x[j] += sx * overlap
                        force_y[j] += sy * overlap
                        force_x[i] -= sx * overlap * 0.1
                        force_y[i] -= sy * overlap * 0.1
                        pushed = True
                    elif b_moving and not a_moving:
                        # Moving B pushes stationary A aside; B barely slows.
                        force_x[i] -= sx * overlap
                        force_y[i] -= sy * overlap
                        force_x[j] += sx * overlap * 0.1
                        force_y[j] += sy * overlap * 0.1
                        pushed = True

                if not pushed:
                    alignment = avx * bvx + avy * bvy

                if not pushed and alignment < _HEAD_ON_THRESH:
                    # Head-on: screen-CW perpendicular of each unit's own velocity.
                    # Screen-CW(vx, vy) = (-vy, vx).
                    # Applying CW to both velocities sends them around each other
                    # in the same rotational sense without cancellation.
                    force_x[i] += -avy * overlap
                    force_y[i] +=  avx * overlap
                    force_x[j] += -bvy * overlap
                    force_y[j] +=  bvx * overlap
                    # Plus a radial half-push so overlap shrinks even when the
                    # paths don't change between ticks (the tangential spin alone
                    # leaves units closing at MOVE_SPEED while drifting sideways
                    # by only `overlap` px — radial keeps the loop convergent).
                    half = overlap * 0.5
                    force_x[i] -= sx * half
                    force_y[i] -= sy * half
                    force_x[j] += sx * half
                    force_y[j] += sy * half
                elif not pushed:
                    # Radial push, blended toward lateral for co-movers.
                    fx, fy = sx, sy

                    if alignment > 0.0:
                        # Average forward direction of the pair.
                        fw_x = avx + bvx
                        fw_y = avy + bvy
                        fw_d = (fw_x * fw_x + fw_y * fw_y) ** 0.5
                        if fw_d > 1e-6:
                            fw_x /= fw_d
                            fw_y /= fw_d
                            # Lateral component of the separation axis.
                            fwd_dot = fx * fw_x + fy * fw_y
                            lat_x   = fx - fwd_dot * fw_x
                            lat_y   = fy - fwd_dot * fw_y
                            lat_d   = (lat_x * lat_x + lat_y * lat_y) ** 0.5
                            if lat_d > 1e-6:
                                lat_x /= lat_d
                                lat_y /= lat_d
                                # Blend: alignment=0 → radial, alignment=1 → lateral.
                                t  = alignment
                                fx = fx * (1.0 - t) + lat_x * t
                                fy = fy * (1.0 - t) + lat_y * t
                                f_d = (fx * fx + fy * fy) ** 0.5
                                if f_d > 1e-6:
                                    fx /= f_d
                                    fy /= f_d

                    half = overlap * 0.5
                    force_x[i] -= fx * half   # push A away from B
                    force_y[i] -= fy * half
                    force_x[j] += fx * half   # push B away from A
                    force_y[j] += fy * half

            else:
                # ---- Avoidance zone: proactive steering (partial RVO) ----
                # closing = d/dt(dist): negative when approaching, positive when diverging.
                closing = -(avx - bvx) * sx - (avy - bvy) * sy
                if closing >= -0.1:
                    continue  # diverging or stationary — no action needed
                proximity = 1.0 - dist / r_avoid      # 0 at edge → 1 at r_sum
                strength  = -closing * proximity * _AVOID_STRENGTH
                # Lateral direction perpendicular to sep axis; pick the side
                # that A's velocity is already leaning toward so both units
                # steer in the same rotational sense (mirrors RVO's shared
                # responsibility).
                lx, ly = -sy, sx
                if avx * lx + avy * ly < 0:
                    lx, ly = sy, -sx
                force_x[i] += lx * strength
                force_y[i] += ly * strength
                force_x[j] -= lx * strength   # B steers the opposite way
                force_y[j] -= ly * strength

    for i, entity in enumerate(dynamics):
        entity.x += force_x[i]
        entity.y += force_y[i]
