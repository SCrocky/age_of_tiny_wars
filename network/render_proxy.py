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

# ---------------------------------------------------------------------------
# Shared display-size constants (mirror the real entity classes)
# ---------------------------------------------------------------------------

_UNIT_SPECS = {
    "Archer":  (96,  20),
    "Warrior": (128, 22),
    "Lancer":  (128, 22),
}
_PAWN_SPEC = (80, 18)

_BUILDING_SPECS = {
    "Castle":   (192, 192, 140, 140, True,  10, 80),  # DW, DH, CW, CH, depot, pop, hbw
    "Archery":  (192, 192, 140, 140, False, 0,  60),
    "Barracks": (192, 192, 140, 140, False, 0,  60),
    "House":    (128, 128, 90,  70,  True,  5,  50),
}

_RESOURCE_DISPLAY = {
    "GoldNode": 96,
    "WoodNode": 112,
    "MeatNode": 80,
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
    COLLISION_W     = 64
    COLLISION_H     = 64
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
        self.amount:       int   = 0
        self._sheep_state: str   = "idle"

        # Blueprint
        self.progress:     float = 0.0
        self._building:    "_BuildingSubProxy | None" = None

        # Arrow
        self._angle:       float = 0.0

    @property
    def depleted(self) -> bool:
        return self.amount <= 0

    @property
    def sort_y(self) -> float:
        if self._building is not None:
            return self._building.y
        return self.y

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
        self.amount       = data.get("amount", 0)
        self._sheep_state = data.get("sheep_state", "idle")

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


def _make_building_cls(name: str, dw, dh, cw, ch, depot, pop, hbw):
    return type(name, (EntityProxy,), {
        "DISPLAY_W":        dw,
        "DISPLAY_H":        dh,
        "COLLISION_W":      cw,
        "COLLISION_H":      ch,
        "is_depot":         depot,
        "pop_bonus":        pop,
        "HEALTH_BAR_WIDTH": hbw,
        "SELECT_RADIUS":    max(dw, dh) // 2,
    })


def _make_resource_cls(name: str, display_size: int, res_type: str):
    return type(name, (EntityProxy,), {
        "DISPLAY_SIZE":  display_size,
        "resource_type": res_type,
    })


_PROXY_CLASSES: dict[str, type] = {}

for _n, (_ds, _sr) in _UNIT_SPECS.items():
    _PROXY_CLASSES[_n] = _make_unit_cls(_n, _ds, _sr)

_PROXY_CLASSES["Pawn"] = _make_unit_cls("Pawn", *_PAWN_SPEC)

for _n, (_dw, _dh, _cw, _ch, _dep, _pop, _hbw) in _BUILDING_SPECS.items():
    _PROXY_CLASSES[_n] = _make_building_cls(_n, _dw, _dh, _cw, _ch, _dep, _pop, _hbw)

for _n, _ds in _RESOURCE_DISPLAY.items():
    _res_type = _n.replace("Node", "").lower()   # "gold", "wood", "meat"
    _PROXY_CLASSES[_n] = _make_resource_cls(_n, _ds, _res_type)

# Blueprint and Arrow use the base class with generic defaults
_PROXY_CLASSES["Blueprint"] = type("Blueprint", (EntityProxy,), {"SELECT_RADIUS": 96})
_PROXY_CLASSES["Arrow"]     = type("Arrow",     (EntityProxy,), {})


def make_proxy(data: dict) -> EntityProxy:
    type_name = data.get("type", "")
    cls = _PROXY_CLASSES.get(type_name, EntityProxy)
    proxy = cls()
    proxy.update_from(data)
    return proxy
