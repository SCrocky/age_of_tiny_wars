"""
Duck-typed entity proxies for client-side rendering.

Each proxy exposes exactly the fields that entity_renderer.py and hud.py read.
Class names match what `type(obj).__name__` returns in those modules (e.g.
"Archer", "Castle", "GoldNode") so avatar look-ups and production menus work
without any changes to the rendering code.

Usage:
    proxy = make_proxy(entity_dict_from_snapshot)
    # proxy behaves like the real entity for rendering purposes
"""

from __future__ import annotations

from entities.archer   import Archer
from entities.warrior  import Warrior
from entities.lancer   import Lancer
from entities.monk     import Monk
from entities.pawn     import Pawn
from entities.building import Archery, Barracks, Castle, House, Monastery, Tower
from entities.resource import GoldNode, WoodNode, MeatNode

# ---------------------------------------------------------------------------
# Display-size specs pulled directly from the entity classes
# ---------------------------------------------------------------------------

_UNIT_SPECS = {
    "Archer":  (Archer.DISPLAY_SIZE,  Archer.SELECT_RADIUS),
    "Warrior": (Warrior.DISPLAY_SIZE, Warrior.SELECT_RADIUS),
    "Lancer":  (Lancer.DISPLAY_SIZE,  Lancer.SELECT_RADIUS),
    "Monk":    (Monk.DISPLAY_SIZE,    Monk.SELECT_RADIUS),
}
_PAWN_SPEC = (Pawn.DISPLAY_SIZE, Pawn.SELECT_RADIUS)

_BUILDING_SPECS = {
    "Castle":    (Castle.DISPLAY_W,    Castle.DISPLAY_H,    Castle.is_depot,    Castle.pop_bonus,    Castle.HEALTH_BAR_WIDTH),
    "Archery":   (Archery.DISPLAY_W,   Archery.DISPLAY_H,   Archery.is_depot,   Archery.pop_bonus,   Archery.HEALTH_BAR_WIDTH),
    "Barracks":  (Barracks.DISPLAY_W,  Barracks.DISPLAY_H,  Barracks.is_depot,  Barracks.pop_bonus,  Barracks.HEALTH_BAR_WIDTH),
    "House":     (House.DISPLAY_W,     House.DISPLAY_H,     House.is_depot,     House.pop_bonus,     House.HEALTH_BAR_WIDTH),
    "Tower":     (Tower.DISPLAY_W,     Tower.DISPLAY_H,     Tower.is_depot,     Tower.pop_bonus,     Tower.HEALTH_BAR_WIDTH),
    "Monastery": (Monastery.DISPLAY_W, Monastery.DISPLAY_H, Monastery.is_depot, Monastery.pop_bonus, Monastery.HEALTH_BAR_WIDTH),
}

_RESOURCE_DISPLAY = {
    "GoldNode": GoldNode.DISPLAY_SIZE,
    "WoodNode": WoodNode.DISPLAY_SIZE,
    "MeatNode": MeatNode.DISPLAY_SIZE,
}

# ---------------------------------------------------------------------------
# Base proxy
# ---------------------------------------------------------------------------

class EntityProxy:
    """Base class — holds all possible fields, most default to harmless values."""

    # Set by subclass factories
    DISPLAY_SIZE    = 96
    SELECT_RADIUS   = 20
    DISPLAY_W       = 64
    DISPLAY_H       = 64
    HEALTH_BAR_WIDTH = 60
    is_depot        = False
    pop_bonus       = 0

    # resource_type used by render_resource duck-dispatch
    resource_type: str | None = None

    def __init__(self):
        self.entity_id:    int   = 0
        self.x:            float = 0.0
        self.y:            float = 0.0
        self.team:         str   = ""
        self.alive:        bool  = True
        self.hp:           int   = 1
        self.max_hp:       int   = 1
        self.selected:     bool  = False
        self.sprite_key:   str   = ""

        # Unit / pawn animation
        self._facing_right: bool  = True
        self._anim_key:     str   = "idle"
        self._frame_idx:    int   = 0
        self._state:        str   = "idle"

        # Lancer-specific
        self._dir_key:     str  = "Right"
        self._flip_dir:    bool = False
        self._def_dir_key: str  = "Right"
        self._def_flip:    bool = False

        # Pawn-specific
        self._task:         str   = "idle"
        self._carried:      float = 0.0
        self._resource_type: str | None = None

        # Resource
        self.amount:        int   = 0
        self._sheep_state:  str   = "idle"
        self._anim_timer:   float = 0.0
        self._target_x:     float = 0.0
        self._target_y:     float = 0.0
        self._speed:        float = 0.0

        # Blueprint
        self.progress:     float = 0.0
        self._building:    "_BuildingSubProxy | None" = None

        # Arrow
        self._angle:       float = 0.0

        # Tower garrison
        self.garrisoned:              bool = False
        # Production building
        self.production_queue: list[str]  = []
        self.production_end:   str | None = None
        self.production_time:  float      = 0.0
        self.garrisoned_anim_key:     str  = "idle"
        self.garrisoned_frame_idx:    int  = 0
        self.garrisoned_facing_right: bool = True

        # Monk heal effect
        self._heal_target_id:    int | None = None
        self._heal_effect_frame: int        = 0
        self._heal_effect_timer: float      = 0.0

    @property
    def depleted(self) -> bool:
        return self.amount <= 0

    @property
    def sort_y(self) -> float:
        if self._building is not None:
            return self._building.y
        return self.y

    def tick_sheep(self, dt: float):
        import math
        from entities.resource import ANIM_FPS, _SHEEP_FRAMES
        # Advance position locally
        if self._speed > 0 and self._sheep_state in ("move", "flee"):
            dx   = self._target_x - self.x
            dy   = self._target_y - self.y
            dist = math.hypot(dx, dy)
            step = self._speed * dt
            if dist <= step:
                self.x, self.y = self._target_x, self._target_y
                self._speed = 0.0
            else:
                self.x += dx / dist * step
                self.y += dy / dist * step
        # Advance animation
        self._anim_timer += dt
        if self._anim_timer >= 1.0 / ANIM_FPS:
            self._anim_timer -= 1.0 / ANIM_FPS
            frame_count       = _SHEEP_FRAMES.get(self._sheep_state, 1)
            self._frame_idx   = (self._frame_idx + 1) % frame_count

    def tick_heal_effect(self, dt: float):
        from entities.monk import ANIM_FPS, FRAME_COUNTS
        if self._heal_target_id is None:
            self._heal_effect_frame = 0
            self._heal_effect_timer = 0.0
            return
        self._heal_effect_timer += dt
        if self._heal_effect_timer >= 1.0 / ANIM_FPS:
            self._heal_effect_timer -= 1.0 / ANIM_FPS
            self._heal_effect_frame = (self._heal_effect_frame + 1) % FRAME_COUNTS["heal"]

    def hit_test(self, sx: float, sy: float, camera) -> bool:
        wx, wy = camera.world_to_screen(self.x, self.y)
        r = self.SELECT_RADIUS * camera.zoom
        dx = sx - wx
        dy = sy - wy
        return dx * dx + dy * dy <= r * r

    def update_from(self, data: dict):
        self.entity_id    = data["id"]
        self.x            = data["x"]
        self.y            = data["y"]
        self.team         = data.get("team") or ""
        self.alive        = data.get("alive", True)
        self.hp           = data.get("hp", 1)
        self.max_hp       = data.get("max_hp", 1)
        self.sprite_key   = data.get("sprite_key", "")

        self._facing_right = data.get("facing_right", True)
        self._anim_key     = data.get("anim_key", "idle")
        self._frame_idx    = data.get("frame_idx", 0)
        self._state        = data.get("state", data.get("anim_key", "idle"))

        # Lancer
        self._dir_key     = data.get("dir_key", "Right")
        self._flip_dir    = data.get("flip_dir", False)
        self._def_dir_key = data.get("def_dir_key", "Right")
        self._def_flip    = data.get("def_flip", False)

        # Pawn
        self._task          = data.get("pawn_task", "idle")
        self._carried       = data.get("pawn_carried", 0)
        self._resource_type = data.get("resource_type")

        # Resource
        self.amount = data.get("amount", 0)
        new_sheep_state = data.get("sheep_state", self._sheep_state)
        if new_sheep_state != self._sheep_state:
            self._sheep_state = new_sheep_state
            self._frame_idx   = 0
            self._anim_timer  = 0.0
        if "target_x" in data:
            self._target_x = data["target_x"]
            self._target_y = data["target_y"]
            self._speed    = data["speed"]

        # Blueprint sub-proxy
        if data.get("type") == "Blueprint":
            self.progress = data.get("progress", 0.0)
            if self._building is None:
                self._building = _BuildingSubProxy()
            self._building.x            = self.x
            self._building.y            = self.y
            self._building.sprite_key   = data.get("sprite_key", "")
            self._building.DISPLAY_W    = data.get("building_display_w", 192)
            self._building.DISPLAY_H    = data.get("building_display_h", 192)
            self._building.max_hp       = self.max_hp

        # Arrow
        self._angle = data.get("angle", 0.0)

        # Tower garrison
        self.garrisoned              = data.get("garrisoned", False)
        self.garrisoned_anim_key     = data.get("garrisoned_anim_key", "idle")
        self.garrisoned_frame_idx    = data.get("garrisoned_frame_idx", 0)
        self.garrisoned_facing_right = data.get("garrisoned_facing_right", True)

        # Production building
        self.production_queue = data.get("production_queue", [])
        self.production_end   = data.get("production_end")
        self.production_time  = data.get("production_time", 0.0)

        # Monk heal effect
        if data.get("type") == "Monk":
            self._heal_target_id = data.get("heal_target_id")


class _BuildingSubProxy:
    """Minimal sub-object to satisfy render_blueprint's access to blueprint._building."""
    def __init__(self):
        self.x:          float = 0.0
        self.y:          float = 0.0
        self.sprite_key: str   = ""
        self.DISPLAY_W:  int   = 192
        self.DISPLAY_H:  int   = 192
        self.max_hp:     int   = 100

    @property
    def sort_y(self): return self.y


# ---------------------------------------------------------------------------
# Typed proxy classes (class name == entity type name for renderer dispatch)
# ---------------------------------------------------------------------------

def _make_unit_cls(name: str, display_size: int, select_radius: int):
    return type(name, (EntityProxy,), {
        "DISPLAY_SIZE":  display_size,
        "SELECT_RADIUS": select_radius,
    })


def _make_building_cls(name: str, dw, dh, depot, pop, hbw):
    return type(name, (EntityProxy,), {
        "DISPLAY_W":        dw,
        "DISPLAY_H":        dh,
        "is_depot":         depot,
        "pop_bonus":        pop,
        "HEALTH_BAR_WIDTH": hbw,
        "SELECT_RADIUS":    max(dw, dh) // 2,
    })


def _resource_hit_test(self, sx: float, sy: float, camera) -> bool:
    wx, wy = camera.world_to_screen(self.x, self.y)
    half = self.DISPLAY_SIZE * camera.zoom / 2
    return abs(sx - wx) <= half and abs(sy - wy) <= half


def _make_resource_cls(name: str, display_size: int, res_type: str):
    return type(name, (EntityProxy,), {
        "DISPLAY_SIZE":  display_size,
        "resource_type": res_type,
        "hit_test":      _resource_hit_test,
    })


_PROXY_CLASSES: dict[str, type] = {}

for _n, (_ds, _sr) in _UNIT_SPECS.items():
    _PROXY_CLASSES[_n] = _make_unit_cls(_n, _ds, _sr)

_PROXY_CLASSES["Pawn"] = _make_unit_cls("Pawn", *_PAWN_SPEC)

for _n, (_dw, _dh, _dep, _pop, _hbw) in _BUILDING_SPECS.items():
    _PROXY_CLASSES[_n] = _make_building_cls(_n, _dw, _dh, _dep, _pop, _hbw)

for _n, _ds in _RESOURCE_DISPLAY.items():
    _res_type = _n.replace("Node", "").lower()   # "gold", "wood", "meat"
    _PROXY_CLASSES[_n] = _make_resource_cls(_n, _ds, _res_type)

# Tower needs extended vision radius for fog-of-war
_PROXY_CLASSES["Tower"].VISION_RADIUS = 10

# WoodNode.sort_y = y + DISPLAY_SIZE/2 (tree bottom), matching the server entity.
# Without this, gathering pawns sort after the tree and render on top of it.
_PROXY_CLASSES["WoodNode"].sort_y = property(
    lambda self: self.y + self.DISPLAY_SIZE / 2
)

# Blueprint and Arrow use the base class with generic defaults
_PROXY_CLASSES["Blueprint"] = type("Blueprint", (EntityProxy,), {"SELECT_RADIUS": 96})
_PROXY_CLASSES["Arrow"]     = type("Arrow",     (EntityProxy,), {})


def make_proxy(data: dict) -> EntityProxy:
    type_name = data.get("type", "")
    cls = _PROXY_CLASSES.get(type_name, EntityProxy)
    proxy = cls()
    proxy.update_from(data)
    return proxy
