"""
Rule-based AI opponent.

Receives parsed GAME_STATE snapshots and returns lists of command dicts.
No asyncio — all pure synchronous decision logic.
"""

import math

TILE_SIZE = 64

TARGET_PAWNS        = 4    # maintain at least this many gatherers
ATTACK_RETARGET     = 30   # re-issue attack order every N snapshots (~3 s)

# --- Combat tuning (grouped so a difficulty layer can override later) ---
DEFEND_RADIUS   = 8 * TILE_SIZE   # enemies this close to the castle trigger defense
RAID_ARMY_MIN   = 3               # start telegraphed raids once we have this many units
RAID_PARTY_SIZE = 2               # units committed per harassment raid
RAID_INTERVAL   = 60              # snapshots between raids (~6 s)
PUSH_ARMY_SIZE  = 8               # mass this many units, then commit everything

_BUILDING_COSTS = {
    "Barracks": {"wood": 50, "gold": 30},
    "Archery":  {"wood": 30, "gold": 20},
    "House":    {"wood": 20},
}

# Resource type -> gather-node type, ranked-scarcest-first in _cmd_gather.
_RES_NODE = {"wood": "WoodNode", "gold": "GoldNode", "meat": "MeatNode"}

# Enemy entity types that are NOT a combat threat to our base.
_BUILDING_TYPES = {"Castle", "Archery", "Barracks", "House", "Blueprint"}
_RESOURCE_TYPES = {"GoldNode", "WoodNode", "MeatNode"}
_NON_THREAT     = _BUILDING_TYPES | _RESOURCE_TYPES | {"Pawn"}


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
        self._raid_tick:   int = -RAID_INTERVAL

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
        # Send each pawn to the scarcest resource it can reach, so all three
        # stockpiles keep flowing instead of every pawn piling on the closest node.
        ranked = sorted(_RES_NODE, key=lambda r: self._eco.get(r, 0))
        cmds = []
        for pawn in idle:
            node = None
            for rtype in ranked:
                candidates = [r for r in self._resources if r["type"] == _RES_NODE[rtype]]
                if candidates:
                    node = min(candidates,
                               key=lambda r: math.hypot(r["x"] - pawn["x"], r["y"] - pawn["y"]))
                    break
            if node is None:  # fallback: nearest node of any type
                node = min(self._resources,
                           key=lambda r: math.hypot(r["x"] - pawn["x"], r["y"] - pawn["y"]))
            cmds.append({"type": "CMD_GATHER", "pawn_ids": [pawn["id"]],
                          "resource_id": node["id"]})
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
        if not self._my_units or not self._enemy:
            return []

        # Phase A — DEFEND: a threatened base overrides everything. Re-targeting
        # every unit (set_attack_target wins over current orders) recalls raiders
        # and pushers back home.
        threats = self._threats_near_base()
        if threats:
            ax, ay = self._attack_anchor()
            target = min(threats, key=lambda e: math.hypot(e["x"] - ax, e["y"] - ay))
            self._attack_tick = tick
            return [{"type": "CMD_ATTACK",
                     "unit_ids": [u["id"] for u in self._my_units],
                     "target_id": target["id"]}]

        idle_units = [u for u in self._my_units if u.get("anim_key") == "idle"]
        if not idle_units:
            return []

        # Phase B — PUSH: once an army is massed, commit it all at the enemy castle.
        if len(self._my_units) >= PUSH_ARMY_SIZE:
            if tick - self._attack_tick < ATTACK_RETARGET:
                return []
            self._attack_tick = tick
            return [self._assault(idle_units, prefer_castle=True)]

        # Phase C — RAID: small, repeated harassment that telegraphs the coming
        # push and gives the human fair warning. Keeps the bulk home as reserve.
        if len(self._my_units) >= RAID_ARMY_MIN and tick - self._raid_tick >= RAID_INTERVAL:
            party = idle_units[:RAID_PARTY_SIZE]
            if party:
                self._raid_tick = tick
                return [self._assault(party, prefer_castle=False)]
        return []

    def _assault(self, units: list[dict], prefer_castle: bool) -> dict:
        """One CMD_ATTACK sending `units` at the nearest enemy (castle if asked)."""
        ax, ay = self._attack_anchor()
        pool   = self._enemy
        if prefer_castle:
            castles = [e for e in self._enemy if e["type"] == "Castle"]
            if castles:
                pool = castles
        target = min(pool, key=lambda e: math.hypot(e["x"] - ax, e["y"] - ay))
        return {"type": "CMD_ATTACK",
                "unit_ids": [u["id"] for u in units],
                "target_id": target["id"]}

    def _threats_near_base(self) -> list[dict]:
        """Enemy mobile combat units within DEFEND_RADIUS of our castle."""
        castle = self._my_castle
        if not castle:
            return []
        return [e for e in self._enemy
                if e["type"] not in _NON_THREAT
                and math.hypot(e["x"] - castle["x"], e["y"] - castle["y"]) <= DEFEND_RADIUS]

    def _attack_anchor(self) -> tuple[float, float]:
        """Origin for closest-enemy ranking: own castle, else centroid of own
        units, else map centre."""
        if self._my_castle:
            return self._my_castle["x"], self._my_castle["y"]
        units = self._my_units + self._my_pawns
        if units:
            return (sum(u["x"] for u in units) / len(units),
                    sum(u["y"] for u in units) / len(units))
        return self._map_w / 2, self._map_h / 2

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
