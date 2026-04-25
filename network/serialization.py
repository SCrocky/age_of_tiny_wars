"""
Msgpack-based serialization for game snapshots and client commands.

Snapshot wire format (dict, msgpack-encoded with 4-byte big-endian length prefix):
  {
    "tick": int,
    "economy": {"blue": {...}, "black": {...}},
    "entities": [
      {
        "id": int,   "type": str,   "x": float, "y": float,
        "hp": int,   "max_hp": int, "team": str, "alive": bool,
        # units / pawns
        "anim_key": str, "frame_idx": int, "facing_right": bool,
        # lancer only
        "dir_key": str, "flip_dir": bool, "def_dir_key": str, "def_flip": bool,
        # buildings
        "sprite_key": str,
        # resources
        "amount": int, "sheep_state": str,
        # blueprints
        "progress": float, "building_sprite_key": str,
        "building_display_w": int, "building_display_h": int,
        # arrows
        "angle": float,
      },
      ...
    ],
    "removed": [int, ...]   # entity_ids that died since last full snapshot
  }

Commands use the same length-prefix framing.
"""

import struct
import msgpack

from entities.building import Building, Castle, Archery, Barracks, House, Tower
from entities.blueprint import Blueprint
from entities.projectile import Arrow
from entities.resource import ResourceNode, GoldNode, WoodNode, MeatNode


def _pack(obj: dict) -> bytes:
    payload = msgpack.packb(obj, use_bin_type=True)
    return struct.pack(">I", len(payload)) + payload


def _unpack(data: bytes) -> dict:
    return msgpack.unpackb(data, raw=False)


def encode_frame(obj: dict) -> bytes:
    """Return a length-prefixed msgpack frame ready for TCP send."""
    return _pack(obj)


def decode_frame(data: bytes) -> dict:
    """Decode the payload bytes of a single frame (no length prefix)."""
    return _unpack(data)


# ---------------------------------------------------------------------------
# Snapshot serialization
# ---------------------------------------------------------------------------

def _serialize_entity(entity) -> dict:
    type_name = type(entity).__name__

    base = {
        "id":    entity.entity_id,
        "type":  type_name,
        "x":     entity.x,
        "y":     entity.y,
        "team":  getattr(entity, "team", None),
        "alive": entity.alive if hasattr(entity, "alive") else True,
    }

    if isinstance(entity, Blueprint):
        base["hp"]     = int(entity.progress)
        base["max_hp"] = entity.max_hp
        base["progress"] = entity.progress
        b = entity._building
        base["sprite_key"]          = b.sprite_key
        base["building_display_w"]  = b.DISPLAY_W
        base["building_display_h"]  = b.DISPLAY_H
        return base

    if isinstance(entity, Tower):
        base["hp"]         = entity.hp
        base["max_hp"]     = entity.max_hp
        base["sprite_key"] = entity.sprite_key
        base["garrisoned"] = entity.garrisoned_archer is not None
        if entity.garrisoned_archer:
            a = entity.garrisoned_archer
            base["garrisoned_anim_key"]    = a._anim_key
            base["garrisoned_frame_idx"]   = a._frame_idx
            base["garrisoned_facing_right"] = a._facing_right
        return base

    if isinstance(entity, Building):
        base["hp"]         = entity.hp
        base["max_hp"]     = entity.max_hp
        base["sprite_key"] = entity.sprite_key
        return base

    if isinstance(entity, Arrow):
        base["angle"] = entity._angle
        base["alive"] = entity.alive
        # arrows have no hp / max_hp
        return base

    if isinstance(entity, ResourceNode):
        base["hp"]     = entity.amount
        base["max_hp"] = entity.max_amount
        base["amount"] = entity.amount
        if not hasattr(entity, "_sheep_state"):
            base["frame_idx"] = entity._frame_idx
        if hasattr(entity, "sprite_key"):
            base["sprite_key"] = entity.sprite_key
        if hasattr(entity, "_sheep_state"):
            base["sheep_state"]  = entity._sheep_state
            base["facing_right"] = entity._facing_right
            base["target_x"]     = entity._target_x
            base["target_y"]     = entity._target_y
            base["speed"]        = entity._speed
        return base

    # Units and Pawns (Entity subclasses with animation state)
    base["hp"]           = entity.hp
    base["max_hp"]       = entity.max_hp
    base["facing_right"] = getattr(entity, "_facing_right", True)
    base["anim_key"]     = getattr(entity, "_anim_key", "idle")
    base["frame_idx"]    = getattr(entity, "_frame_idx", 0)

    # Lancer-specific directional attack/defence state
    if type_name == "Lancer":
        base["dir_key"]     = entity._dir_key
        base["flip_dir"]    = entity._flip_dir
        base["def_dir_key"] = entity._def_dir_key
        base["def_flip"]    = entity._def_flip

    # Pawn-specific fields used by renderer
    if type_name == "Pawn":
        task = getattr(entity, "_task", None)
        base["pawn_task"]     = task.value if hasattr(task, "value") else "idle"
        base["pawn_carried"]  = getattr(entity, "_carried", 0)
        base["resource_type"] = getattr(entity, "_resource_type", None)

    return base


def serialize_snapshot(game, tick: int) -> bytes:
    entities = []
    for lst in (game.buildings, game.blueprints, game.units, game.pawns,
                game.arrows, game.resources):
        for e in lst:
            entities.append(_serialize_entity(e))

    snapshot = {
        "type":     "GAME_STATE",
        "tick":     tick,
        "economy":  game.economy,
        "entities": entities,
    }
    return encode_frame(snapshot)


# ---------------------------------------------------------------------------
# Command serialization
# ---------------------------------------------------------------------------

def deserialize_command(data: bytes) -> dict:
    return decode_frame(data)
