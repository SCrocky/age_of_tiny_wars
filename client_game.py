"""
Client-side game state. Receives server snapshots and renders them.
Does NOT run any simulation — no update(), no pathfinding, no entity logic.

Selection state is purely local (never sent to server).
Camera pan/zoom is local.
All player actions (move, attack, spawn…) are encoded as command dicts
placed in _cmd_queue; client_main.py drains this queue and sends them.
"""

import queue
import time

import pygame
from pygame._sdl2.video import Renderer

from camera import Camera, InputSnapshot, Viewport
from map import TileMap, TILE_SIZE
from rendering.map_renderer import MapRenderer
from rendering.hud_renderer import HUD

import rendering.entity_renderer as entity_renderer
import texture_cache
from network.render_proxy import EntityProxy, make_proxy
from systems.fog import FogOfWar


DRAG_THRESHOLD = 5


class ClientGame:
    def __init__(self, renderer: Renderer, scene: dict, player_team: str,
                 viewport: Viewport):
        self.renderer    = renderer
        self.viewport    = viewport
        self.w           = 1600
        self.h           = 900
        self.player_team = player_team

        self.map          = TileMap.from_data(scene["cols"], scene["rows"], scene["tiles"])
        self.camera       = Camera(self.w, self.h)
        self.camera.x     = (self.map.pixel_width  - self.w) / 2
        self.camera.y     = (self.map.pixel_height - self.h) / 2
        self._camera_on_castle = False

        self._map_renderer = MapRenderer()
        self.hud           = HUD(viewport.window_w, viewport.window_h)

        self._proxies: dict[int, EntityProxy] = {}

        self._buildings:  list[EntityProxy] = []
        self._blueprints: list[EntityProxy] = []
        self._units:      list[EntityProxy] = []
        self._pawns:      list[EntityProxy] = []
        self._arrows:     list[EntityProxy] = []
        self._resources:  list[EntityProxy] = []

        self._snap_prev:   dict | None = None
        self._snap_curr:   dict | None = None
        self._snap_prev_by_id: dict[int, dict] = {}
        self._snap_curr_by_id: dict[int, dict] = {}
        self._t_prev:      float = 0.0
        self._t_curr:      float = 0.0

        self.economy: dict = {
            "blue":  {"gold": 0, "wood": 0, "meat": 0, "pop": 0, "pop_cap": 0},
            "black": {"gold": 0, "wood": 0, "meat": 0, "pop": 0, "pop_cap": 0},
        }

        self._cmd_queue: queue.Queue = queue.Queue()

        self._drag_start: tuple[int, int] | None = None
        self._dragging:   bool = False
        self._pending_build: str | None = None
        self._current_mouse_pos: tuple[int, int] = (0, 0)
        self.debug: bool = False

        self.fog = FogOfWar(self.map.rows, self.map.cols)

        self._winner: str | None = None

        self._connected: bool = True
        self._rtt_ms: float | None = None
        self._show_debug: bool = False

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
            self._rtt_ms = (time.monotonic() - msg.get("client_time", 0)) * 1000

    def _apply_snapshot(self, snap: dict):
        now = time.monotonic()

        self._snap_prev       = self._snap_curr
        self._snap_prev_by_id = self._snap_curr_by_id
        self._t_prev          = self._t_curr
        self._snap_curr       = snap
        self._snap_curr_by_id = {d["id"]: d for d in snap.get("entities", [])}
        self._t_curr          = now

        eco = snap.get("economy")
        if eco:
            self.economy = eco

        incoming_ids = set()
        for data in snap.get("entities", []):
            eid = data["id"]
            incoming_ids.add(eid)
            if eid in self._proxies:
                self._proxies[eid].update_from(data)
            else:
                self._proxies[eid] = make_proxy(data)

        for dead_id in set(self._proxies) - incoming_ids:
            del self._proxies[dead_id]

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

        self._buildings.clear()
        self._blueprints.clear()
        self._units.clear()
        self._pawns.clear()
        self._arrows.clear()
        self._resources.clear()

        for proxy in self._proxies.values():
            t = type(proxy).__name__
            if t in ("Castle", "Archery", "Barracks", "House", "Tower", "Monastery"):
                self._buildings.append(proxy)
            elif t == "Blueprint":
                self._blueprints.append(proxy)
            elif t in ("Archer", "Warrior", "Lancer", "Monk"):
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
        if self._snap_prev is None or self._t_curr == self._t_prev:
            return proxy.x, proxy.y

        elapsed = time.monotonic() - self._t_curr
        interval = self._t_curr - self._t_prev
        alpha = min(1.0, elapsed / max(0.001, interval))

        prev_data = self._snap_prev_by_id.get(proxy.entity_id)
        if prev_data is None:
            return proxy.x, proxy.y

        px = prev_data["x"] + (proxy.x - prev_data["x"]) * alpha
        py = prev_data["y"] + (proxy.y - prev_data["y"]) * alpha
        return px, py

    def _apply_lerp(self):
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
            return

        if event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            self._current_mouse_pos = event.pos

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
            elif event.key == pygame.K_s:
                lx, ly = self.viewport.to_logical(*self._current_mouse_pos)
                wx, wy = self.camera.screen_to_world(lx, ly)
                self._cmd_queue.put({
                    "type":    "CMD_DEV_SPAWN",
                    "world_x": wx,
                    "world_y": wy,
                })
            elif event.key == pygame.K_h:
                castle = next(
                    (b for b in self._buildings
                     if type(b).__name__ == "Castle" and b.team == self.player_team),
                    None,
                )
                if castle is not None:
                    self.camera.x = castle.x - self.w / 2 / self.camera.zoom
                    self.camera.y = castle.y - self.h / 2 / self.camera.zoom

        elif event.type == pygame.MOUSEWHEEL:
            lx, ly = self.viewport.to_logical(*self._current_mouse_pos)
            self.camera.zoom_at(lx, ly, event.y)
            self.hud.on_zoom_changed()

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
                    elif action == "spawn_monk":
                        self._emit_spawn("Monk")
                    elif action == "release_archer":
                        self._emit_release()
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
        keys = pygame.key.get_pressed()
        lx, ly = self.viewport.to_logical(*self._current_mouse_pos)
        inp = InputSnapshot(
            pan_left  = bool(keys[pygame.K_LEFT]),
            pan_right = bool(keys[pygame.K_RIGHT]),
            pan_up    = bool(keys[pygame.K_UP]),
            pan_down  = bool(keys[pygame.K_DOWN]),
            mouse_x   = lx,
            mouse_y   = ly,
        )
        self.camera.update(dt, self.map.pixel_width, self.map.pixel_height, inp)

        for sheep in self._resources:
            if type(sheep).__name__ == "MeatNode":
                sheep.tick_sheep(dt)

        for unit in self._units:
            if type(unit).__name__ == "Monk":
                unit.tick_heal_effect(dt)

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
        sx, sy = self.viewport.to_logical(*screen_pos)
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
        sx1, sy1 = self.viewport.to_logical(*start)
        sx2, sy2 = self.viewport.to_logical(*end)
        x1, x2 = min(sx1, sx2), max(sx1, sx2)
        y1, y2 = min(sy1, sy2), max(sy1, sy2)
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
        sx, sy = self.viewport.to_logical(*screen_pos)
        wx, wy = self.camera.screen_to_world(sx, sy)

        sel_units = [u for u in self._units if u.selected and u.team == self.player_team]
        sel_pawns = [p for p in self._pawns if p.selected and p.team == self.player_team]

        # Garrison: right-click own Tower with selected Archers
        sel_archers = [u for u in sel_units if type(u).__name__ == "Archer"]
        own_tower = next(
            (b for b in self._buildings
             if type(b).__name__ == "Tower" and b.team == self.player_team
             and b.hit_test(sx, sy, self.camera)),
            None,
        )
        if own_tower and sel_archers:
            self._cmd_queue.put({
                "type":       "CMD_GARRISON",
                "archer_ids": [a.entity_id for a in sel_archers],
                "tower_id":   own_tower.entity_id,
            })
            return

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

        blueprint = next(
            (b for b in self._blueprints
             if b.team == self.player_team and b.alive and b.hit_test(sx, sy, self.camera)),
            None,
        )
        if blueprint and sel_pawns:
            self._cmd_queue.put({
                "type":         "CMD_ASSIGN_BUILD",
                "pawn_ids":     [p.entity_id for p in sel_pawns],
                "blueprint_id": blueprint.entity_id,
            })
            return

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

    def _emit_release(self):
        sel_tower = next(
            (b for b in self._buildings
             if b.selected and b.team == self.player_team
             and type(b).__name__ == "Tower"),
            None,
        )
        if sel_tower:
            self._cmd_queue.put({
                "type":     "CMD_RELEASE",
                "tower_id": sel_tower.entity_id,
            })

    def _emit_build(self, screen_pos):
        name = self._pending_build
        self._pending_build = None
        sx, sy = self.viewport.to_logical(*screen_pos)
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
    # Fog visibility
    # ------------------------------------------------------------------

    def _fog_visible(self, obj) -> bool:
        team = getattr(obj, "team", None)
        if team == self.player_team:
            return True
        t = type(obj).__name__
        if t in ("Castle", "Archery", "Barracks", "House", "Tower", "Monastery",
                 "Blueprint", "GoldNode", "WoodNode"):
            return self.fog.is_explored(obj.x, obj.y, TILE_SIZE)
        return self.fog.is_visible(obj.x, obj.y, TILE_SIZE)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self):
        renderer = self.renderer
        cam      = self.camera

        self.viewport.apply_window(renderer)
        renderer.draw_color = (10, 20, 40, 255)
        renderer.clear()

        self.viewport.apply_world(renderer)
        self._map_renderer.render(self.map, renderer, cam)

        margin = 200
        vx0 = cam.x - margin
        vy0 = cam.y - margin
        vx1 = cam.x + self.w / cam.zoom + margin
        vy1 = cam.y + self.h / cam.zoom + margin

        world_objects = [
            obj for obj in
            self._resources + self._blueprints + self._buildings + self._units + self._pawns
            if vx0 <= obj.x <= vx1 and vy0 <= obj.y <= vy1
            and self._fog_visible(obj)
        ]
        world_objects.sort(key=lambda obj: obj.sort_y)

        self._apply_lerp()
        try:
            for obj in world_objects:
                t = type(obj).__name__
                if t in ("Castle", "Archery", "Barracks", "House", "Tower", "Monastery"):
                    entity_renderer.render_building(obj, renderer, cam)
                elif t == "Blueprint":
                    entity_renderer.render_blueprint(obj, renderer, cam)
                elif t in ("GoldNode", "WoodNode", "MeatNode"):
                    entity_renderer.render_resource(obj, renderer, cam)
                elif t == "Pawn":
                    entity_renderer.render_pawn(obj, renderer, cam)
                elif t == "Archer":
                    entity_renderer.render_archer(obj, renderer, cam)
                elif t == "Warrior":
                    entity_renderer.render_warrior(obj, renderer, cam)
                elif t == "Lancer":
                    entity_renderer.render_lancer(obj, renderer, cam)
                elif t == "Monk":
                    entity_renderer.render_monk(obj, renderer, cam)

            # Heal effects rendered on top of all entities
            for monk in self._units:
                if type(monk).__name__ == "Monk" and monk._heal_target_id:
                    target = self._proxies.get(monk._heal_target_id)
                    if target and target.alive:
                        entity_renderer.render_heal_effect(
                            target, monk._heal_effect_frame, monk.team, renderer, cam
                        )

            for arrow in self._arrows:
                if self.fog.is_visible(arrow.x, arrow.y, TILE_SIZE):
                    entity_renderer.render_arrow(arrow, renderer, cam)
        finally:
            self._restore_lerp()

        friendly = [e for e in self._units + self._pawns + self._buildings
                    if e.team == self.player_team]
        self._map_renderer.render_fog(self.fog, self.map, renderer, cam, friendly)

        # Switch to window-pixel space for HUD and overlays.
        self.viewport.apply_window(renderer)
        win_w = self.viewport.window_w
        win_h = self.viewport.window_h

        if self._pending_build:
            txt_surf = self._font_hint.render(
                f"Right-click to place {self._pending_build}  (ESC to cancel)",
                True, (255, 220, 80),
            )
            txt_tex = texture_cache.make_texture(txt_surf)
            tw, th  = txt_surf.get_size()
            txt_tex.draw(dstrect=(win_w // 2 - tw // 2, 56, tw, th))

        self._draw_drag_box()

        all_selectable = self._units + self._pawns + self._buildings
        self.hud.draw(renderer, self.economy, all_selectable, self.player_team)

        col = (80, 140, 255) if self.player_team == "blue" else (60, 60, 60)
        txt_surf = self._font_team.render(f"You: {self.player_team}", True, col)
        txt_tex  = texture_cache.make_texture(txt_surf)
        tw, th   = txt_surf.get_size()
        txt_tex.draw(dstrect=(win_w - tw - 10, 10, tw, th))

        if not self._connected:
            self._draw_disconnect_overlay()

        if self._show_debug and self._rtt_ms is not None:
            rtt_surf = self._font_debug.render(f"RTT: {self._rtt_ms:.0f}ms", True, (200, 200, 200))
            rtt_tex  = texture_cache.make_texture(rtt_surf)
            tw, th   = rtt_surf.get_size()
            rtt_tex.draw(dstrect=(win_w - tw - 10, 30, tw, th))

        if self._winner:
            self._draw_winner()

    def _draw_drag_box(self):
        if not self._dragging or not self._drag_start:
            return
        mx, my = self._current_mouse_pos
        sx, sy = self._drag_start
        x1 = min(sx, mx)
        y1 = min(sy, my)
        w  = abs(mx - sx)
        h  = abs(my - sy)
        if w < 2 or h < 2:
            return
        renderer = self.renderer
        renderer.draw_blend_mode = pygame.BLENDMODE_BLEND
        renderer.draw_color = (100, 220, 100, 40)
        renderer.fill_rect(pygame.Rect(x1, y1, w, h))
        renderer.draw_color = (100, 220, 100, 255)
        renderer.draw_rect(pygame.Rect(x1, y1, w, h))
        renderer.draw_blend_mode = pygame.BLENDMODE_NONE

    def _draw_disconnect_overlay(self):
        renderer = self.renderer
        win_w = self.viewport.window_w
        win_h = self.viewport.window_h
        renderer.draw_blend_mode = pygame.BLENDMODE_BLEND
        renderer.draw_color = (40, 0, 0, 180)
        renderer.fill_rect(pygame.Rect(0, win_h // 2 - 30, win_w, 60))
        renderer.draw_blend_mode = pygame.BLENDMODE_NONE
        font     = pygame.font.SysFont(None, 36)
        txt_surf = font.render("Connection lost — reconnecting…", True, (255, 180, 80))
        txt_tex  = texture_cache.make_texture(txt_surf)
        tw, th   = txt_surf.get_size()
        txt_tex.draw(dstrect=(win_w // 2 - tw // 2, win_h // 2 - th // 2, tw, th))

    def _draw_winner(self):
        renderer = self.renderer
        win_w = self.viewport.window_w
        win_h = self.viewport.window_h
        renderer.draw_blend_mode = pygame.BLENDMODE_BLEND
        renderer.draw_color = (0, 0, 0, 140)
        renderer.fill_rect(pygame.Rect(0, 0, win_w, win_h))
        renderer.draw_blend_mode = pygame.BLENDMODE_NONE
        font = pygame.font.SysFont(None, 80)
        if self._winner == self.player_team:
            txt_surf = font.render("Victory!", True, (255, 220, 80))
        else:
            txt_surf = font.render("Defeat", True, (200, 80, 80))
        txt_tex = texture_cache.make_texture(txt_surf)
        tw, th  = txt_surf.get_size()
        txt_tex.draw(dstrect=(win_w // 2 - tw // 2, win_h // 2 - th // 2, tw, th))
