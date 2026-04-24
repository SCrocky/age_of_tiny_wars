"""
Rule-based AI opponent.

Receives parsed GAME_STATE snapshots and returns lists of command dicts.
No asyncio — all pure synchronous decision logic.
"""

import math

TILE_SIZE = 64

TARGET_PAWNS        = 4    # maintain at least this many gatherers
ATTACK_RETARGET     = 30   # re-issue attack order every N snapshots (~3 s)

_BUILDING_COSTS = {
    "Barracks": {"wood": 50, "gold": 30},
    "Archery":  {"wood": 30, "gold": 20},
    "House":    {"wood": 20},
}


class BotAI:
    def __init__(self, team: str, map_cols: int, map_rows: int):
        self.team      = team
        self._map_w    = map_cols * TILE_SIZE
        self._map_h    = map_rows * TILE_SIZE

        # Parsed snapshot views (repopulated each tick)
        self._eco:            dict = {}
        self._my_castle:      dict | None = None
        self._my_buildings:   list = []
        self._my_pawns:       list = []
        self._my_units:       list = []
        self._my_blueprints:  list = []
        self._enemy:          list = []
        self._resources:      list = []

        # Build tracking
        self._build_pending:  set[str] = set()   # types issued but not yet completed
        self._house_slots:    int      = 0        # number of houses requested so far

        self._attack_tick: int = -ATTACK_RETARGET

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def apply_snapshot(self, snap: dict) -> list[dict]:
        self._parse(snap)
        tick = snap.get("tick", 0)
        cmds: list[dict] = []
        cmds += self._cmd_gather()
        cmds += self._cmd_spawn()
        cmds += self._cmd_build()
        cmds += self._cmd_attack(tick)
        return cmds

    # ------------------------------------------------------------------
    # Snapshot parsing
    # ------------------------------------------------------------------

    def _parse(self, snap: dict):
        self._eco = snap.get("economy", {}).get(self.team, {})
        entities  = snap.get("entities", [])

        mine  = [e for e in entities if e.get("team") == self.team]
        enemy = [e for e in entities if e.get("team") not in (None, "", self.team)
                 and e.get("alive", True)]

        self._my_buildings  = [e for e in mine if e["type"] in ("Castle", "Archery", "Barracks", "House") and e.get("alive", True)]
        self._my_castle     = next((b for b in self._my_buildings if b["type"] == "Castle"), None)
        self._my_pawns      = [e for e in mine if e["type"] == "Pawn"   and e.get("alive", True)]
        self._my_units      = [e for e in mine if e["type"] in ("Archer", "Warrior", "Lancer") and e.get("alive", True)]
        self._my_blueprints = [e for e in mine if e["type"] == "Blueprint" and e.get("alive", True)]
        self._enemy         = enemy
        self._resources     = [e for e in entities
                                if e["type"] in ("GoldNode", "WoodNode", "MeatNode")
                                and e.get("amount", 0) > 0]

        # Retire pending entries for building types that now exist
        existing_types = {b["type"] for b in self._my_buildings}
        self._build_pending -= existing_types

    # ------------------------------------------------------------------
    # Decisions
    # ------------------------------------------------------------------

    def _can_afford(self, cost: dict) -> bool:
        return all(self._eco.get(k, 0) >= v for k, v in cost.items())

    def _cmd_gather(self) -> list[dict]:
        idle = [p for p in self._my_pawns if p.get("pawn_task") == "idle"]
        if not idle or not self._resources:
            return []
        cmds = []
        for pawn in idle:
            res = min(self._resources,
                      key=lambda r: math.hypot(r["x"] - pawn["x"], r["y"] - pawn["y"]))
            cmds.append({"type": "CMD_GATHER", "pawn_ids": [pawn["id"]],
                          "resource_id": res["id"]})
        return cmds

    def _cmd_spawn(self) -> list[dict]:
        eco     = self._eco
        pop     = eco.get("pop", 0)
        pop_cap = eco.get("pop_cap", 0)
        if pop >= pop_cap:
            return []

        castle = self._my_castle

        # Priority 1 — keep pawns stocked
        if len(self._my_pawns) < TARGET_PAWNS and self._can_afford({"meat": 20}) and castle:
            return [{"type": "CMD_SPAWN", "building_id": castle["id"],
                     "unit_type": "Pawn"}]

        # Priority 2 — combat units
        by_type = {b["type"]: b for b in self._my_buildings}
        if "Barracks" in by_type and self._can_afford({"wood": 45, "meat": 10}):
            return [{"type": "CMD_SPAWN", "building_id": by_type["Barracks"]["id"],
                     "unit_type": "Lancer"}]
        if "Archery" in by_type and self._can_afford({"wood": 15, "meat": 30}):
            return [{"type": "CMD_SPAWN", "building_id": by_type["Archery"]["id"],
                     "unit_type": "Archer"}]
        return []

    def _cmd_build(self) -> list[dict]:
        castle = self._my_castle
        if not castle:
            return []

        # Need a spare pawn not currently gathering
        idle_pawns = [p for p in self._my_pawns if p.get("pawn_task") == "idle"]
        if not idle_pawns:
            return []

        eco        = self._eco
        pop        = eco.get("pop", 0)
        pop_cap    = eco.get("pop_cap", 0)
        by_type    = {b["type"] for b in self._my_buildings}
        pawn       = idle_pawns[0]

        # Build order: Barracks → Archery → Houses (as needed)
        for btype in ("Barracks", "Archery"):
            if btype not in by_type and btype not in self._build_pending:
                if self._can_afford(_BUILDING_COSTS[btype]):
                    wx, wy = self._placement_pos(len(self._build_pending))
                    self._build_pending.add(btype)
                    return [{"type": "CMD_BUILD", "pawn_ids": [pawn["id"]],
                             "building_type": btype, "world_x": wx, "world_y": wy}]

        # Build a House when population headroom is tight
        if pop >= pop_cap - 2 and self._can_afford({"wood": 20}):
            slot = self._house_slots
            n_houses = sum(1 for b in self._my_buildings if b["type"] == "House")
            if n_houses + len([b for b in self._build_pending if b == "House"]) <= slot:
                wx, wy = self._placement_pos(3 + slot)
                self._house_slots += 1
                self._build_pending.add("House")
                return [{"type": "CMD_BUILD", "pawn_ids": [pawn["id"]],
                         "building_type": "House", "world_x": wx, "world_y": wy}]
        return []

    def _cmd_attack(self, tick: int) -> list[dict]:
        if tick - self._attack_tick < ATTACK_RETARGET:
            return []
        idle_units = [u for u in self._my_units if u.get("anim_key") == "idle"]
        if not idle_units or not self._enemy:
            return []

        target = (next((e for e in self._enemy if e["type"] == "Castle"), None)
                  or self._enemy[0])
        self._attack_tick = tick
        return [{"type": "CMD_ATTACK",
                 "unit_ids": [u["id"] for u in idle_units],
                 "target_id": target["id"]}]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _placement_pos(self, slot: int) -> tuple[float, float]:
        """
        Return a world position for the nth building, fanning out from
        the castle towards the centre of the map.
        """
        castle = self._my_castle
        cx, cy = castle["x"], castle["y"]
        # Step inward toward the horizontal centre
        dx = 1 if cx < self._map_w / 2 else -1
        wx = cx + dx * (3 + slot * 3) * TILE_SIZE
        wy = cy
        return wx, wy
