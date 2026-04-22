import json
import math
import random
import pygame
from camera import Camera
from map import TileMap, TILE_SIZE
from entities.archer import Archer
from entities.lancer import Lancer
from entities.warrior import Warrior
from entities.pawn import Pawn, Task as PawnTask
from entities.building import Building, Castle, Archery, Barracks, House
from entities.resource import GoldNode, WoodNode, MeatNode
from entities.projectile import Arrow
from entities.blueprint import Blueprint, BUILDABLE
from systems.pathfinding import astar
from systems.fog import FogOfWar
from rendering.hud_renderer import HUD
import rendering.entity_renderer as entity_renderer
from rendering.map_renderer import MapRenderer

_BUILDING_CLS = {
    "Castle":   Castle,
    "Archery":  Archery,
    "Barracks": Barracks,
    "House":    House,
}
_UNIT_CLS = {
    "Archer":  Archer,
    "Lancer":  Lancer,
    "Warrior": Warrior,
}

DRAG_THRESHOLD = 5


class Game:
    def __init__(self, screen: pygame.Surface, scene_path: str, headless: bool = False):
        self.screen = screen
        self.w = screen.get_width()
        self.h = screen.get_height()

        self.font         = pygame.font.SysFont(None, 22)
        self.hud          = HUD(self.w, self.h)
        self._map_renderer = MapRenderer()

        self.units:      list           = []
        self.pawns:      list[Pawn]     = []
        self.arrows:     list[Arrow]    = []
        self.buildings:  list[Building] = []
        self.blueprints: list[Blueprint]= []
        self.resources:  list           = []

        self.economy: dict[str, dict[str, int]] = {
            "blue":  {"gold": 60, "wood": 60, "meat": 60, "pop": 0, "pop_cap": 0},
            "black": {"gold": 60, "wood": 60, "meat": 60, "pop": 0, "pop_cap": 0},
        }

        self.headless: bool = headless
        self._next_entity_id: int = 1
        self._load_scene(scene_path)
        self.fog = FogOfWar(self.map.rows, self.map.cols)

        self._drag_start: tuple[int, int] | None = None
        self._dragging: bool = False
        self._pending_build: str | None = None
        self.debug: bool = False
        self._last_dt: float = 1 / 60

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _assign_id(self, entity):
        entity.entity_id = self._next_entity_id
        self._next_entity_id += 1
        return entity

    def _center_camera(self):
        self.camera = Camera(self.w, self.h)
        self.camera.x = (self.map.pixel_width  - self.w) / 2
        self.camera.y = (self.map.pixel_height - self.h) / 2

    def _load_scene(self, path: str):
        with open(path) as f:
            scene = json.load(f)

        self.map = TileMap.from_data(scene["cols"], scene["rows"], scene["tiles"])
        self._center_camera()

        for b_data in scene.get("buildings", []):
            cls = _BUILDING_CLS.get(b_data["type"])
            if cls is None:
                continue
            kw = {}
            if b_data["type"] == "House":
                kw["variant"] = b_data.get("variant", 1)
            building = self._assign_id(cls(b_data["x"], b_data["y"], team=b_data["team"], **kw))
            self.map.clear_area(building.x, building.y, tile_radius=4)
            building.on_place(self.map)
            self.buildings.append(building)

        for u_data in scene.get("units", []):
            x, y, team = u_data["x"], u_data["y"], u_data["team"]
            if u_data["type"] == "Pawn":
                self.pawns.append(self._assign_id(Pawn(x, y, team=team)))
            else:
                cls = _UNIT_CLS.get(u_data["type"])
                if cls:
                    self.units.append(self._assign_id(cls(x, y, team=team)))

        for r_data in scene.get("resources", []):
            x, y, variant = r_data["x"], r_data["y"], r_data.get("variant", 0)
            rtype = r_data["type"]
            if rtype == "wood":
                self.resources.append(self._assign_id(WoodNode(x, y, variant=variant)))
            elif rtype == "gold":
                self.resources.append(self._assign_id(GoldNode(x, y, variant=variant)))
            elif rtype == "meat":
                self.resources.append(self._assign_id(MeatNode(x, y)))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _all_selectable(self):
        return self.units + self.pawns + self.buildings

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if self._pending_build:
                    self._pending_build = None
                else:
                    pygame.event.post(pygame.event.Event(pygame.QUIT))
            elif event.key == pygame.K_d:
                self.debug = not self.debug

        elif event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            self.camera.zoom_at(mx, my, event.y)

        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                self._drag_start = event.pos
                self._dragging = False
            elif event.button == 3:
                self._handle_right_click(event.pos)

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                if self._dragging:
                    self._handle_box_select(self._drag_start, event.pos)
                else:
                    action = self.hud.handle_click(*event.pos)
                    if action and action.startswith("spawn_"):
                        self._spawn_unit(action[6:].capitalize())
                    elif action and action.startswith("build_"):
                        name = action[6:]
                        self._pending_build = name[0].upper() + name[1:]
                    else:
                        self._pending_build = None
                        self._handle_left_click(event.pos)
                self._drag_start = None
                self._dragging = False

        elif event.type == pygame.MOUSEMOTION:
            if self._drag_start:
                dx = event.pos[0] - self._drag_start[0]
                dy = event.pos[1] - self._drag_start[1]
                if dx * dx + dy * dy > DRAG_THRESHOLD**2:
                    self._dragging = True

    # ------------------------------------------------------------------
    # Click handlers
    # ------------------------------------------------------------------

    def _handle_left_click(self, screen_pos):
        sx, sy = screen_pos
        clicked = next(
            (
                u
                for u in self._all_selectable()
                if u.team == "blue" and u.hit_test(sx, sy, self.camera)
            ),
            None,
        )
        mods = pygame.key.get_mods()
        if not (mods & pygame.KMOD_SHIFT):
            for u in self._all_selectable():
                u.selected = False
        if clicked:
            clicked.selected = (
                not clicked.selected if (mods & pygame.KMOD_SHIFT) else True
            )

    def _handle_box_select(self, start, end):
        x1, x2 = min(start[0], end[0]), max(start[0], end[0])
        y1, y2 = min(start[1], end[1]), max(start[1], end[1])
        mods = pygame.key.get_mods()
        if not (mods & pygame.KMOD_SHIFT):
            for u in self._all_selectable():
                u.selected = False
        for u in self.units + self.pawns:
            if u.team != "blue":
                continue
            ux, uy = self.camera.world_to_screen(u.x, u.y)
            if x1 <= ux <= x2 and y1 <= uy <= y2:
                u.selected = True

    # unit_type -> (unit_class, cost_dict, required_building_class_or_None)
    _SPAWN_TABLE = {
        "Pawn":    (Pawn,    {"meat": 20},                None),
        "Archer":  (Archer,  {"wood": 15, "meat": 30},    Archery),
        "Lancer":  (Lancer,  {"wood": 45, "meat": 10},    Barracks),
        "Warrior": (Warrior, {"gold": 35, "meat": 40},    Barracks),
    }

    def _spawn_unit(self, unit_type: str, team: str = "blue", building=None):
        unit_cls, costs, building_cls = self._SPAWN_TABLE[unit_type]
        eco = self.economy[team]
        if eco["pop"] >= eco["pop_cap"]:
            return
        if any(eco.get(r, 0) < amt for r, amt in costs.items()):
            return
        spawn_building = building or next(
            (b for b in self.buildings
             if b.team == team and b.selected and b.alive
             and (building_cls is None or isinstance(b, building_cls))),
            None,
        )
        if spawn_building is None:
            return
        for r, amt in costs.items():
            eco[r] -= amt
        angle = random.uniform(0, 2 * math.pi)
        unit = self._assign_id(unit_cls(
            spawn_building.x + math.cos(angle) * 120,
            spawn_building.y + math.sin(angle) * 120,
            team=team,
        ))
        (self.pawns if unit_cls is Pawn else self.units).append(unit)


    def _place_blueprint(self, screen_pos):
        name = self._pending_build
        self._pending_build = None
        cls, costs = BUILDABLE[name]
        eco = self.economy["blue"]
        if not all(eco.get(k, 0) >= v for k, v in costs.items()):
            return
        for k, v in costs.items():
            eco[k] -= v
        sx, sy = screen_pos
        wx, wy = self.camera.screen_to_world(sx, sy)
        building = cls(wx, wy, team="blue")
        self.map.clear_area(wx, wy, tile_radius=4)
        bp = self._assign_id(Blueprint(building))
        self.blueprints.append(bp)
        for pawn in self.pawns:
            if pawn.selected and pawn.team == "blue":
                pawn.assign_build(bp)

    def _handle_right_click(self, screen_pos):
        if self._pending_build:
            self._place_blueprint(screen_pos)
            return
        sx, sy = screen_pos
        wx, wy = self.camera.screen_to_world(sx, sy)

        selected_combat = [u for u in self.units if u.selected]
        selected_pawns = [p for p in self.pawns if p.selected]

        # Right-click on enemy unit or building → attack (combat units only)
        enemy = next(
            (
                e
                for e in self.units + self.pawns + self.buildings
                if e.team != "blue" and e.hit_test(sx, sy, self.camera)
            ),
            None,
        )
        if enemy and selected_combat:
            for unit in selected_combat:
                unit.set_attack_target(enemy)
            return

        # Right-click on a resource node → gather (pawns only)
        has_depot = any(b.is_depot and b.team == "blue" and b.alive for b in self.buildings)
        if has_depot and selected_pawns:
            resource = next(
                (
                    r
                    for r in self.resources
                    if not r.depleted and r.hit_test(sx, sy, self.camera)
                ),
                None,
            )
            if resource:
                for pawn in selected_pawns:
                    pawn.assign_gather(resource, self.buildings)
                return

        # Otherwise → move (all selected blue units + pawns)
        goal_col = max(0, min(int(wx // TILE_SIZE), self.map.cols - 1))
        goal_row = max(0, min(int(wy // TILE_SIZE), self.map.rows - 1))
        all_selected = selected_combat + selected_pawns
        offsets = self._formation_offsets(len(all_selected))
        for unit, (dc, dr) in zip(all_selected, offsets):
            target = self.map.nearest_walkable(goal_col + dc, goal_row + dr)
            start_tile = (int(unit.x // TILE_SIZE), int(unit.y // TILE_SIZE))
            path = astar(self.map, start_tile, target)
            unit.set_path(path)

    @staticmethod
    def _formation_offsets(count: int) -> list[tuple[int, int]]:
        offsets = [(0, 0)]
        ring = 1
        while len(offsets) < count:
            for dc in range(-ring, ring + 1):
                for dr in range(-ring, ring + 1):
                    if max(abs(dc), abs(dr)) == ring:
                        offsets.append((dc, dr))
                        if len(offsets) == count:
                            return offsets
            ring += 1
        return offsets[:count]

    def _fog_visible(self, obj) -> bool:
        """Return True if obj should be rendered given current fog state."""
        team = getattr(obj, "team", None)
        if team == "blue":
            return True
        # Static objects (buildings, blueprints, resources): show once explored
        if isinstance(obj, (Building, Blueprint, GoldNode, WoodNode, MeatNode)):
            return self.fog.is_explored(obj.x, obj.y, TILE_SIZE)
        # Enemy mobile units: only when currently visible
        return self.fog.is_visible(obj.x, obj.y, TILE_SIZE)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def _recalc_pop(self):
        for team in ("blue", "black"):
            eco = self.economy[team]
            eco["pop"] = sum(1 for u in self.units + self.pawns if u.team == team)
            eco["pop_cap"] = sum(
                b.pop_bonus
                for b in self.buildings
                if b.team == team and b.alive and b.pop_bonus > 0
            )

    def update(self, dt: float):
        self._last_dt = dt
        if not self.headless:
            keys = pygame.key.get_pressed()
            mx, my = pygame.mouse.get_pos()
            from camera import InputSnapshot
            inp = InputSnapshot(
                pan_left  = bool(keys[pygame.K_LEFT]),
                pan_right = bool(keys[pygame.K_RIGHT]),
                pan_up    = bool(keys[pygame.K_UP]),
                pan_down  = bool(keys[pygame.K_DOWN]),
                mouse_x   = mx,
                mouse_y   = my,
            )
            self.camera.update(dt, self.map.pixel_width, self.map.pixel_height, inp)

        for unit in self.units:
            new_arrows = unit.update(dt, self.map)
            for arrow in new_arrows:
                self._assign_id(arrow)
            self.arrows.extend(new_arrows)

        for pawn in self.pawns:
            deposit = pawn.update(dt, self.map)
            for resource_type, amount in deposit.items():
                self.economy[pawn.team][resource_type] += amount

        for arrow in self.arrows:
            arrow.update(dt)

        for res in self.resources:
            res.update(dt)

        self._apply_separation(dt)
        self._apply_building_collision()

        next_buildings  = []
        next_blueprints = []
        for bp in self.blueprints:
            if bp.alive and bp.progress >= bp.max_hp:
                building = self._assign_id(bp.complete())
                building.on_place(self.map)
                next_buildings.append(building)
            elif bp.alive:
                next_blueprints.append(bp)
        for b in self.buildings:
            if b.alive:
                next_buildings.append(b)
            else:
                b.on_destroy(self.map)
        self.buildings  = next_buildings
        self.blueprints = next_blueprints

        self.units  = [u for u in self.units  if u.alive]
        self.pawns  = [p for p in self.pawns  if p.alive]
        self.arrows = [a for a in self.arrows if a.alive]
        self._recalc_pop()

        if not self.headless:
            friendly = [e for e in self.units + self.pawns + self.buildings if e.team == "blue"]
            self.fog.update(friendly, TILE_SIZE)

    def _apply_building_collision(self):
        for unit in self.units + self.pawns:
            r = unit.DISPLAY_SIZE / 4
            for building in self.buildings + self.blueprints:
                hw = building.COLLISION_W / 2 + r
                hh = building.COLLISION_H / 2 + r
                dx = unit.x - building.x
                dy = unit.y - building.y
                ox = hw - abs(dx)
                oy = hh - abs(dy)
                if ox > 0 and oy > 0:
                    if ox <= oy:
                        unit.x += ox * (1 if dx >= 0 else -1)
                    else:
                        unit.y += oy * (1 if dy >= 0 else -1)

    def _apply_separation(self, dt: float):
        RADIUS = 52.0
        FORCE = 180.0
        all_units = self.units + self.pawns
        for i, a in enumerate(all_units):
            fx = fy = 0.0
            for j, b in enumerate(all_units):
                if i == j:
                    continue
                dx = a.x - b.x
                dy = a.y - b.y
                dist = math.hypot(dx, dy)
                if 0 < dist < RADIUS:
                    strength = (RADIUS - dist) / RADIUS
                    fx += dx / dist * strength
                    fy += dy / dist * strength
            new_x = a.x + fx * FORCE * dt
            new_y = a.y + fy * FORCE * dt
            if self.map.is_walkable(int(new_x // TILE_SIZE), int(a.y // TILE_SIZE)):
                a.x = new_x
            if self.map.is_walkable(int(a.x // TILE_SIZE), int(new_y // TILE_SIZE)):
                a.y = new_y

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def render(self):
        self.screen.fill((10, 20, 40))
        self._map_renderer.render(self.map, self.screen, self.camera)

        # Frustum cull: skip objects entirely outside the visible world rectangle.
        cam     = self.camera
        margin  = 200  # world-px margin to avoid pop-in for large sprites
        vx0     = cam.x - margin
        vy0     = cam.y - margin
        vx1     = cam.x + self.w / cam.zoom + margin
        vy1     = cam.y + self.h / cam.zoom + margin

        # Y-sort all world objects so lower objects draw on top (painter's algorithm)
        world_objects = [
            obj for obj in
            self.resources + self.blueprints + self.buildings + self.units + self.pawns
            if vx0 <= obj.x <= vx1 and vy0 <= obj.y <= vy1
            and self._fog_visible(obj)
        ]
        world_objects.sort(key=lambda obj: obj.sort_y)
        for obj in world_objects:
            if isinstance(obj, Building):
                entity_renderer.render_building(obj, self.screen, self.camera)
            elif isinstance(obj, Blueprint):
                entity_renderer.render_blueprint(obj, self.screen, self.camera)
            elif isinstance(obj, (GoldNode, WoodNode, MeatNode)):
                entity_renderer.render_resource(obj, self.screen, self.camera)
            else:
                obj.render(self.screen, self.camera)

        for arrow in self.arrows:
            if self.fog.is_visible(arrow.x, arrow.y, TILE_SIZE):
                entity_renderer.render_arrow(arrow, self.screen, self.camera)

        friendly = [e for e in self.units + self.pawns + self.buildings if e.team == "blue"]
        self._map_renderer.render_fog(self.fog, self.map, self.screen, self.camera, friendly)

        if self._pending_build:
            font = pygame.font.SysFont(None, 28)
            txt  = font.render(
                f"Right-click to place {self._pending_build}  (ESC to cancel)",
                True, (255, 220, 80),
            )
            self.screen.blit(txt, (self.w // 2 - txt.get_width() // 2, 56))

        self._draw_drag_box()
        if self.debug:
            self._draw_debug()
        self.hud.draw(self.screen, self.economy, self._all_selectable())

    def _draw_drag_box(self):
        if not self._dragging or not self._drag_start:
            return
        mx, my = pygame.mouse.get_pos()
        x1 = min(self._drag_start[0], mx)
        y1 = min(self._drag_start[1], my)
        w = abs(mx - self._drag_start[0])
        h = abs(my - self._drag_start[1])
        if w < 2 or h < 2:
            return
        box = pygame.Surface((w, h), pygame.SRCALPHA)
        box.fill((100, 220, 100, 40))
        self.screen.blit(box, (x1, y1))
        pygame.draw.rect(self.screen, (100, 220, 100), (x1, y1, w, h), 1)

    def _draw_debug(self):
        font = pygame.font.SysFont(None, 18)
        ts = TILE_SIZE

        fps = 1.0 / self._last_dt if self._last_dt > 0 else 0
        stats = (
            f"FPS: {fps:.0f}  "
            f"units: {len(self.units)}  pawns: {len(self.pawns)}  "
            f"buildings: {len(self.buildings)}  arrows: {len(self.arrows)}  "
            f"resources: {len(self.resources)}"
        )
        surf = font.render(stats, True, (200, 255, 200))
        self.screen.blit(surf, (8, 8))

        # Blocked tiles
        tile_px = max(1, int(ts * self.camera.zoom))
        overlay = pygame.Surface((tile_px, tile_px), pygame.SRCALPHA)
        overlay.fill((255, 60, 60, 80))
        for col, row in self.map.blocked:
            sx, sy = self.camera.world_to_screen(col * ts, row * ts)
            self.screen.blit(overlay, (int(sx), int(sy)))
            pygame.draw.rect(
                self.screen, (255, 60, 60), (int(sx), int(sy), tile_px, tile_px), 1
            )

        for pawn in self.pawns:
            px, py = self.camera.world_to_screen(pawn.x, pawn.y)

            # Path line
            if pawn.path:
                pts = [(px, py)]
                for col, row in pawn.path:
                    wx = col * ts + ts / 2
                    wy = row * ts + ts / 2
                    pts.append(self.camera.world_to_screen(wx, wy))
                pygame.draw.lines(self.screen, (255, 255, 0), False, pts, 1)
                # Goal tile
                gc, gr = pawn.path[-1]
                gx, gy = self.camera.world_to_screen(gc * ts + ts / 2, gr * ts + ts / 2)
                pygame.draw.circle(self.screen, (255, 255, 0), (int(gx), int(gy)), 5)

            # Target position (resource or depot)
            target = None
            task = pawn._task
            if task is PawnTask.TO_RESOURCE and pawn._resource_node:
                target = (pawn._resource_node.x, pawn._resource_node.y)
                color = (0, 220, 255)
            elif task is PawnTask.GATHER and pawn._resource_node:
                target = (pawn._resource_node.x, pawn._resource_node.y)
                color = (0, 255, 100)
            elif task is PawnTask.TO_DEPOT:
                depot = pawn._nearest_depot()
                if depot:
                    target = (depot.x, depot.y)
                color = (255, 100, 0)

            if target:
                tx, ty = self.camera.world_to_screen(*target)
                pygame.draw.line(
                    self.screen, color, (int(px), int(py)), (int(tx), int(ty)), 1
                )
                pygame.draw.circle(self.screen, color, (int(tx), int(ty)), 6, 2)

            # State label
            label = (
                f"{task or 'idle'}  carry={int(pawn._carried)}  path={len(pawn.path)}"
            )
            surf = font.render(label, True, (255, 255, 100))
            self.screen.blit(surf, (int(px) - surf.get_width() // 2, int(py) - 55))

            # Deposit radius ring on the pawn
            r = int(pawn.DEPOSIT_RADIUS * self.camera.zoom)
            pygame.draw.circle(self.screen, (255, 120, 0), (int(px), int(py)), r, 1)

