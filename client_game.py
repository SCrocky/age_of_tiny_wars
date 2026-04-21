"""
Client-side game state. Receives server snapshots and renders them.
Does NOT run any simulation — no update(), no pathfinding, no entity logic.

Selection state is purely local (never sent to server).
Camera pan/zoom is local.
All player actions (move, attack, spawn…) are encoded as command dicts
placed in _cmd_queue; client_main.py drains this queue and sends them.
"""

import json
import queue
import time

import pygame

from camera import Camera, InputSnapshot
from map import TileMap, TILE_SIZE
from rendering.map_renderer import MapRenderer
from rendering.hud_renderer import HUD
import rendering.entity_renderer as entity_renderer
from network.render_proxy import EntityProxy, make_proxy
from systems.fog import FogOfWar

DRAG_THRESHOLD = 5


class ClientGame:
    def __init__(self, screen: pygame.Surface, scene: dict, player_team: str):
        self.screen      = screen
        self.w           = screen.get_width()
        self.h           = screen.get_height()
        self.player_team = player_team

        self.map          = TileMap.from_data(scene["cols"], scene["rows"], scene["tiles"])
        self.camera       = Camera(self.w, self.h)
        self.camera.x     = (self.map.pixel_width  - self.w) / 2
        self.camera.y     = (self.map.pixel_height - self.h) / 2
        self._camera_on_castle = False  # snap to own castle on first snapshot

        self._map_renderer = MapRenderer()
        self.hud           = HUD(self.w, self.h)

        # Proxy registry keyed by entity_id
        self._proxies: dict[int, EntityProxy] = {}

        # Typed render lists (rebuilt each apply_snapshot call)
        self._buildings:  list[EntityProxy] = []
        self._blueprints: list[EntityProxy] = []
        self._units:      list[EntityProxy] = []   # Archer, Warrior, Lancer
        self._pawns:      list[EntityProxy] = []
        self._arrows:     list[EntityProxy] = []
        self._resources:  list[EntityProxy] = []

        # Snapshot interpolation
        self._snap_prev:   dict | None = None
        self._snap_curr:   dict | None = None
        self._t_prev:      float = 0.0
        self._t_curr:      float = 0.0

        # Latest economy (for HUD)
        self.economy: dict = {
            "blue":  {"gold": 0, "wood": 0, "meat": 0, "pop": 0, "pop_cap": 0},
            "black": {"gold": 0, "wood": 0, "meat": 0, "pop": 0, "pop_cap": 0},
        }

        # Command queue — drained by client_main.py and sent to server
        self._cmd_queue: queue.Queue = queue.Queue()

        # Input / selection state
        self._drag_start: tuple[int, int] | None = None
        self._dragging:   bool = False
        self._pending_build: str | None = None
        self.debug: bool = False

        self.fog = FogOfWar(self.map.rows, self.map.cols)

        # Game-over overlay
        self._winner: str | None = None

        # Connection state
        self._connected: bool = True
        self._rtt_ms: float | None = None
        self._show_debug: bool = False

        # Cached fonts (avoid re-creating SysFont every frame)
        self._font_hint  = pygame.font.SysFont(None, 28)
        self._font_team  = pygame.font.SysFont(None, 22)
        self._font_debug = pygame.font.SysFont(None, 20)

    # ------------------------------------------------------------------
    # Snapshot application
    # ------------------------------------------------------------------

    def apply_message(self, msg: dict):
        msg_type = msg.get("type")
        if msg_type == "GAME_STATE":
            self._apply_snapshot(msg)
        elif msg_type == "GAME_OVER":
            self._winner = msg.get("winner", "")
        elif msg_type == "DISCONNECTED":
            self._connected = False
        elif msg_type == "RECONNECTED":
            self._connected = True
        elif msg_type == "PONG":
            import time
            self._rtt_ms = (time.monotonic() - msg.get("client_time", 0)) * 1000

    def _apply_snapshot(self, snap: dict):
        now = time.monotonic()

        # Slide the interpolation window
        self._snap_prev = self._snap_curr
        self._t_prev    = self._t_curr
        self._snap_curr = snap
        self._t_curr    = now

        # Update economy
        eco = snap.get("economy")
        if eco:
            self.economy = eco

        # Reconcile proxy registry
        incoming_ids = set()
        for data in snap.get("entities", []):
            eid = data["id"]
            incoming_ids.add(eid)
            if eid in self._proxies:
                self._proxies[eid].update_from(data)
            else:
                self._proxies[eid] = make_proxy(data)

        # Remove entities that no longer exist
        for dead_id in set(self._proxies) - incoming_ids:
            del self._proxies[dead_id]

        # On the first snapshot, snap the camera to the player's own castle
        if not self._camera_on_castle:
            for data in snap.get("entities", []):
                if (data.get("type") == "Castle"
                        and data.get("team") == self.player_team):
                    cx = data["x"] - self.w / 2 / self.camera.zoom
                    cy = data["y"] - self.h / 2 / self.camera.zoom
                    self.camera.x = cx
                    self.camera.y = cy
                    self._camera_on_castle = True
                    break

        # Rebuild typed render lists
        self._buildings.clear()
        self._blueprints.clear()
        self._units.clear()
        self._pawns.clear()
        self._arrows.clear()
        self._resources.clear()

        for proxy in self._proxies.values():
            t = type(proxy).__name__
            if t in ("Castle", "Archery", "Barracks", "House"):
                self._buildings.append(proxy)
            elif t == "Blueprint":
                self._blueprints.append(proxy)
            elif t in ("Archer", "Warrior", "Lancer"):
                self._units.append(proxy)
            elif t == "Pawn":
                self._pawns.append(proxy)
            elif t == "Arrow":
                self._arrows.append(proxy)
            elif t in ("GoldNode", "WoodNode", "MeatNode"):
                self._resources.append(proxy)

    # ------------------------------------------------------------------
    # Interpolated position
    # ------------------------------------------------------------------

    def _lerped_pos(self, proxy: EntityProxy) -> tuple[float, float]:
        """Linearly interpolate between the last two snapshots."""
        if self._snap_prev is None or self._t_curr == self._t_prev:
            return proxy.x, proxy.y

        elapsed = time.monotonic() - self._t_curr
        interval = self._t_curr - self._t_prev
        alpha = min(1.0, elapsed / max(0.001, interval))

        eid = proxy.entity_id
        prev_data = None
        if self._snap_prev:
            for d in self._snap_prev.get("entities", []):
                if d["id"] == eid:
                    prev_data = d
                    break

        if prev_data is None:
            return proxy.x, proxy.y

        px = prev_data["x"] + (proxy.x - prev_data["x"]) * alpha
        py = prev_data["y"] + (proxy.y - prev_data["y"]) * alpha
        return px, py

    def _apply_lerp(self):
        """Temporarily write interpolated positions into proxies before rendering."""
        self._lerp_stash: list[tuple[EntityProxy, float, float]] = []
        for lst in (self._units, self._pawns, self._arrows):
            for proxy in lst:
                lx, ly = self._lerped_pos(proxy)
                self._lerp_stash.append((proxy, proxy.x, proxy.y))
                proxy.x, proxy.y = lx, ly

    def _restore_lerp(self):
        for proxy, ox, oy in self._lerp_stash:
            proxy.x, proxy.y = ox, oy

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event):
        if self._winner:
            return  # no input after game over

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if self._pending_build:
                    self._pending_build = None
                else:
                    pygame.event.post(pygame.event.Event(pygame.QUIT))
            elif event.key == pygame.K_d:
                self.debug = not self.debug
            elif event.key == pygame.K_F3:
                self._show_debug = not self._show_debug

        elif event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            self.camera.zoom_at(mx, my, event.y)

        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                self._drag_start = event.pos
                self._dragging   = False
            elif event.button == 3:
                self._handle_right_click(event.pos)

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                if self._dragging:
                    self._handle_box_select(self._drag_start, event.pos)
                else:
                    action = self.hud.handle_click(*event.pos)
                    if action == "spawn_pawn":
                        self._emit_spawn("Pawn")
                    elif action == "spawn_archer":
                        self._emit_spawn("Archer")
                    elif action == "spawn_lancer":
                        self._emit_spawn("Lancer")
                    elif action == "spawn_warrior":
                        self._emit_spawn("Warrior")
                    elif action and action.startswith("build_"):
                        name = action[6:]
                        self._pending_build = name[0].upper() + name[1:]
                    else:
                        self._pending_build = None
                        self._handle_left_click(event.pos)
                self._drag_start = None
                self._dragging   = False

        elif event.type == pygame.MOUSEMOTION:
            if self._drag_start:
                dx = event.pos[0] - self._drag_start[0]
                dy = event.pos[1] - self._drag_start[1]
                if dx * dx + dy * dy > DRAG_THRESHOLD ** 2:
                    self._dragging = True

    def update(self, dt: float):
        """Update camera pan/zoom (local only)."""
        keys = pygame.key.get_pressed()
        mx, my = pygame.mouse.get_pos()
        inp = InputSnapshot(
            pan_left  = bool(keys[pygame.K_LEFT]),
            pan_right = bool(keys[pygame.K_RIGHT]),
            pan_up    = bool(keys[pygame.K_UP]),
            pan_down  = bool(keys[pygame.K_DOWN]),
            mouse_x   = mx,
            mouse_y   = my,
        )
        self.camera.update(dt, self.map.pixel_width, self.map.pixel_height, inp)

        friendly = [e for e in self._units + self._pawns + self._buildings
                    if e.team == self.player_team]
        self.fog.update(friendly, TILE_SIZE)

    # ------------------------------------------------------------------
    # Click handlers
    # ------------------------------------------------------------------

    def _my_entities(self, include_buildings: bool = False):
        lst = self._units + self._pawns
        if include_buildings:
            lst = lst + self._buildings
        return [e for e in lst if e.team == self.player_team]

    def _handle_left_click(self, screen_pos):
        sx, sy = screen_pos
        all_mine = self._my_entities(include_buildings=True)
        clicked = next(
            (e for e in all_mine if e.hit_test(sx, sy, self.camera)),
            None,
        )
        mods = pygame.key.get_mods()
        if not (mods & pygame.KMOD_SHIFT):
            for e in all_mine:
                e.selected = False
        if clicked:
            clicked.selected = (
                not clicked.selected if (mods & pygame.KMOD_SHIFT) else True
            )

    def _handle_box_select(self, start, end):
        if start is None:
            return
        x1, x2 = min(start[0], end[0]), max(start[0], end[0])
        y1, y2 = min(start[1], end[1]), max(start[1], end[1])
        mods = pygame.key.get_mods()
        if not (mods & pygame.KMOD_SHIFT):
            for e in self._my_entities(include_buildings=True):
                e.selected = False
        for e in self._units + self._pawns:
            if e.team != self.player_team:
                continue
            ux, uy = self.camera.world_to_screen(e.x, e.y)
            if x1 <= ux <= x2 and y1 <= uy <= y2:
                e.selected = True

    def _handle_right_click(self, screen_pos):
        if self._pending_build:
            self._emit_build(screen_pos)
            return
        sx, sy = screen_pos
        wx, wy = self.camera.screen_to_world(sx, sy)

        sel_units = [u for u in self._units if u.selected and u.team == self.player_team]
        sel_pawns = [p for p in self._pawns if p.selected and p.team == self.player_team]

        # Attack enemy
        enemy = next(
            (e for e in self._units + self._pawns + self._buildings
             if e.team != self.player_team and e.hit_test(sx, sy, self.camera)),
            None,
        )
        if enemy and sel_units:
            self._cmd_queue.put({
                "type":     "CMD_ATTACK",
                "unit_ids": [u.entity_id for u in sel_units],
                "target_id": enemy.entity_id,
            })
            return

        # Gather resource
        resource = next(
            (r for r in self._resources
             if not r.depleted and r.hit_test(sx, sy, self.camera)),
            None,
        )
        if resource and sel_pawns:
            self._cmd_queue.put({
                "type":       "CMD_GATHER",
                "pawn_ids":   [p.entity_id for p in sel_pawns],
                "resource_id": resource.entity_id,
            })
            return

        # Move
        goal_col = max(0, min(int(wx // TILE_SIZE), self.map.cols - 1))
        goal_row = max(0, min(int(wy // TILE_SIZE), self.map.rows - 1))
        all_sel = sel_units + sel_pawns
        if all_sel:
            self._cmd_queue.put({
                "type":     "CMD_MOVE",
                "unit_ids": [u.entity_id for u in all_sel],
                "goal_col": goal_col,
                "goal_row": goal_row,
            })

    def _emit_spawn(self, unit_type: str):
        """Find the selected building of this player and emit a spawn command."""
        sel_building = next(
            (b for b in self._buildings if b.selected and b.team == self.player_team),
            None,
        )
        if sel_building is None:
            return
        self._cmd_queue.put({
            "type":       "CMD_SPAWN",
            "building_id": sel_building.entity_id,
            "unit_type":   unit_type,
        })

    def _emit_build(self, screen_pos):
        name = self._pending_build
        self._pending_build = None
        sx, sy = screen_pos
        wx, wy = self.camera.screen_to_world(sx, sy)
        sel_pawns = [p.entity_id for p in self._pawns
                     if p.selected and p.team == self.player_team]
        self._cmd_queue.put({
            "type":          "CMD_BUILD",
            "pawn_ids":      sel_pawns,
            "building_type": name,
            "world_x":       wx,
            "world_y":       wy,
        })

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _fog_visible(self, obj) -> bool:
        team = getattr(obj, "team", None)
        if team == self.player_team:
            return True
        t = type(obj).__name__
        if t in ("Castle", "Archery", "Barracks", "House", "Blueprint",
                 "GoldNode", "WoodNode"):
            return self.fog.is_explored(obj.x, obj.y, TILE_SIZE)
        return self.fog.is_visible(obj.x, obj.y, TILE_SIZE)

    def render(self):
        self.screen.fill((10, 20, 40))
        self._map_renderer.render(self.map, self.screen, self.camera)

        cam    = self.camera
        margin = 200
        vx0 = cam.x - margin
        vy0 = cam.y - margin
        vx1 = cam.x + self.w / cam.zoom + margin
        vy1 = cam.y + self.h / cam.zoom + margin

        # Collect visible world objects, filtered by fog, then Y-sort
        world_objects = [
            obj for obj in
            self._resources + self._blueprints + self._buildings + self._units + self._pawns
            if vx0 <= obj.x <= vx1 and vy0 <= obj.y <= vy1
            and self._fog_visible(obj)
        ]
        world_objects.sort(key=lambda obj: obj.sort_y)

        # Apply interpolation for moving entities
        self._apply_lerp()
        try:
            for obj in world_objects:
                t = type(obj).__name__
                if t in ("Castle", "Archery", "Barracks", "House"):
                    entity_renderer.render_building(obj, self.screen, cam)
                elif t == "Blueprint":
                    entity_renderer.render_blueprint(obj, self.screen, cam)
                elif t in ("GoldNode", "WoodNode", "MeatNode"):
                    entity_renderer.render_resource(obj, self.screen, cam)
                elif t == "Pawn":
                    entity_renderer.render_pawn(obj, self.screen, cam)
                elif t == "Archer":
                    entity_renderer.render_archer(obj, self.screen, cam)
                elif t == "Warrior":
                    entity_renderer.render_warrior(obj, self.screen, cam)
                elif t == "Lancer":
                    entity_renderer.render_lancer(obj, self.screen, cam)

            for arrow in self._arrows:
                if self.fog.is_visible(arrow.x, arrow.y, TILE_SIZE):
                    entity_renderer.render_arrow(arrow, self.screen, cam)
        finally:
            self._restore_lerp()

        friendly = [e for e in self._units + self._pawns + self._buildings
                    if e.team == self.player_team]
        self._map_renderer.render_fog(self.fog, self.map, self.screen, cam, friendly)

        # Pending build hint
        if self._pending_build:
            txt = self._font_hint.render(
                f"Right-click to place {self._pending_build}  (ESC to cancel)",
                True, (255, 220, 80),
            )
            self.screen.blit(txt, (self.w // 2 - txt.get_width() // 2, 56))

        # Drag box
        self._draw_drag_box()

        # HUD — pass all selectable proxies
        all_selectable = self._units + self._pawns + self._buildings
        self.hud.draw(self.screen, self.economy, all_selectable, self.player_team)

        # Team indicator
        col = (80, 140, 255) if self.player_team == "blue" else (60, 60, 60)
        txt = self._font_team.render(f"You: {self.player_team}", True, col)
        self.screen.blit(txt, (self.w - txt.get_width() - 10, 10))

        # Disconnect overlay
        if not self._connected:
            self._draw_disconnect_overlay()

        # Debug overlay (F3)
        if self._show_debug and self._rtt_ms is not None:
            rtt = self._font_debug.render(f"RTT: {self._rtt_ms:.0f}ms", True, (200, 200, 200))
            self.screen.blit(rtt, (self.w - rtt.get_width() - 10, 30))

        # Game-over overlay
        if self._winner:
            self._draw_winner()

    def _draw_drag_box(self):
        if not self._dragging or not self._drag_start:
            return
        mx, my = pygame.mouse.get_pos()
        x1 = min(self._drag_start[0], mx)
        y1 = min(self._drag_start[1], my)
        w  = abs(mx - self._drag_start[0])
        h  = abs(my - self._drag_start[1])
        if w < 2 or h < 2:
            return
        box = pygame.Surface((w, h), pygame.SRCALPHA)
        box.fill((100, 220, 100, 40))
        self.screen.blit(box, (x1, y1))
        pygame.draw.rect(self.screen, (100, 220, 100), (x1, y1, w, h), 1)

    def _draw_disconnect_overlay(self):
        overlay = pygame.Surface((self.w, 60), pygame.SRCALPHA)
        overlay.fill((40, 0, 0, 180))
        self.screen.blit(overlay, (0, self.h // 2 - 30))
        font = pygame.font.SysFont(None, 36)
        txt = font.render("Connection lost — reconnecting…", True, (255, 180, 80))
        self.screen.blit(txt, (self.w // 2 - txt.get_width() // 2, self.h // 2 - txt.get_height() // 2))

    def _draw_winner(self):
        overlay = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        self.screen.blit(overlay, (0, 0))
        font = pygame.font.SysFont(None, 80)
        if self._winner == self.player_team:
            txt = font.render("Victory!", True, (255, 220, 80))
        else:
            txt = font.render("Defeat", True, (200, 80, 80))
        self.screen.blit(txt, (self.w // 2 - txt.get_width() // 2,
                                self.h // 2 - txt.get_height() // 2))
