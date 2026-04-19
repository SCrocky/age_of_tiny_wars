import math
import random
import pygame
from camera import Camera
from map import TileMap, TILE_SIZE, GRASS
from entities.archer import Archer
from entities.lancer import Lancer
from entities.warrior import Warrior
from entities.pawn import Pawn
from entities.building import Building, Castle, Archery, Barracks, House
from entities.resource import GoldNode, WoodNode, MeatNode
from entities.projectile import Arrow
from entities.blueprint import Blueprint, BUILDABLE
from systems.pathfinding import astar
from hud import HUD

DRAG_THRESHOLD = 5


class Game:
    MAP_COLS = 50
    MAP_ROWS = 40

    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self.w = screen.get_width()
        self.h = screen.get_height()

        self.map = TileMap(self.MAP_COLS, self.MAP_ROWS)
        self.camera = Camera(self.w, self.h)
        self.camera.x = (self.map.pixel_width - self.w) / 2
        self.camera.y = (self.map.pixel_height - self.h) / 2

        self.font = pygame.font.SysFont(None, 22)
        self.hud  = HUD(self.w, self.h)

        self.units: list = []
        self.pawns: list[Pawn] = []
        self.arrows: list[Arrow] = []
        self.buildings: list[Building] = []
        self.blueprints: list[Blueprint] = []
        self.resources: list = []

        # Economy: resource counts per team
        self.economy: dict[str, dict[str, int]] = {
            "blue":  {"gold": 0, "wood": 0, "meat": 0, "pop": 0, "pop_cap": 0},
            "black": {"gold": 0, "wood": 0, "meat": 0, "pop": 0, "pop_cap": 0},
        }

        self._spawn_world()

        self._drag_start: tuple[int, int] | None = None
        self._dragging: bool = False
        self._pending_build: str | None = None
        self.debug: bool = False
        self._last_dt: float = 1 / 60

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _spawn_world(self):
        cx = self.map.pixel_width // 2
        cy = self.map.pixel_height // 2

        # --- Castles ---
        blue_castle   = Castle(cx - 400, cy, team="blue")
        black_castle  = Castle(cx + 400, cy, team="black")
        blue_archery  = Archery(cx - 220, cy + 160, team="blue")
        blue_barracks = Barracks(cx - 570, cy + 150, team="blue")
        blue_houses = [
            House(cx - 620, cy - 130, team="blue", variant=1),
            House(cx - 490, cy - 160, team="blue", variant=2),
            House(cx - 360, cy - 150, team="blue", variant=3),
        ]
        self.buildings = [blue_castle, black_castle, blue_archery, blue_barracks] + blue_houses

        for b in self.buildings:
            self.map.clear_area(b.x, b.y, tile_radius=4)

        # --- Player combat units (spawned to the right of the blue castle) ---
        for dx, dy in [(-100, -80), (-20, -80), (60, -80)]:
            self.units.append(Archer(cx + dx, cy + dy, team="blue"))
        for dx, dy in [(-60, 80), (20, 80)]:
            self.units.append(Lancer(cx + dx, cy + dy, team="blue"))
        for dx, dy in [(-20, 0), (60, 0)]:
            self.units.append(Warrior(cx + dx, cy + dy, team="blue"))

        # --- Enemy combat units (spawned to the left of the black castle) ---
        for dx, dy in [(100, -80), (20, -80), (-60, -80)]:
            self.units.append(Archer(cx + dx, cy + dy, team="black"))
        for dx, dy in [(60, 80), (-20, 80)]:
            self.units.append(Lancer(cx + dx, cy + dy, team="black"))
        for dx, dy in [(20, 0), (-60, 0)]:
            self.units.append(Warrior(cx + dx, cy + dy, team="black"))

        # --- Player pawns (to the left of the blue castle, outside its footprint) ---
        for dx, dy in [(-580, -60), (-620, 0), (-580, 60)]:
            self.pawns.append(Pawn(cx + dx, cy + dy, team="blue"))

        # --- Resource nodes (shared map, accessible to both sides) ---
        rng = random.Random()
        border = 5

        def rand_grass_pos():
            for _ in range(100):
                col = rng.randint(border, self.MAP_COLS - border - 1)
                row = rng.randint(border, self.MAP_ROWS - border - 1)
                if self.map.is_walkable(col, row):
                    return (
                        col * TILE_SIZE + TILE_SIZE // 2,
                        row * TILE_SIZE + TILE_SIZE // 2,
                    )
            return cx, cy

        MIN_RESOURCE_DIST = 56.0

        def spawn_clumps(num_clumps, clump_min, clump_max, radius, factory):
            for _ in range(num_clumps):
                cx, cy = rand_grass_pos()
                count       = rng.randint(clump_min, clump_max)
                start_angle = rng.uniform(0, 2 * math.pi)
                spread      = count - 1  # resources surrounding the center
                for i in range(count):
                    if i == 0:
                        x, y = cx, cy
                    else:
                        angle = start_angle + (i - 1) * (2 * math.pi / spread)
                        dist  = rng.uniform(radius * 0.5, radius)
                        x = cx + math.cos(angle) * dist
                        y = cy + math.sin(angle) * dist
                    col, row = int(x // TILE_SIZE), int(y // TILE_SIZE)
                    if self.map.tile_at(col, row) != GRASS:
                        continue
                    if any(math.hypot(r.x - x, r.y - y) < MIN_RESOURCE_DIST
                           for r in self.resources):
                        continue
                    self.resources.append(factory(x, y))

        spawn_clumps(4, 1, 3, 90,  lambda x, y: GoldNode(x, y, variant=rng.randint(1, 6)))
        spawn_clumps(6, 3, 5, 90,  lambda x, y: WoodNode(x, y, variant=rng.randint(0, 3)))
        spawn_clumps(3, 2, 5, 80,  lambda x, y: MeatNode(x, y))

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
                    if action == "spawn_pawn":
                        self._handle_spawn_pawn()
                    elif action == "spawn_archer":
                        self._handle_spawn_archer()
                    elif action == "spawn_lancer":
                        self._handle_spawn_lancer()
                    elif action == "spawn_warrior":
                        self._handle_spawn_warrior()
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

    def _handle_spawn_archer(self):
        eco = self.economy["blue"]
        if eco["wood"] < 15 or eco["meat"] < 30 or eco["pop"] >= eco["pop_cap"]:
            return
        archery = next(
            (b for b in self.buildings if b.team == "blue"
             and b.selected and b.alive and isinstance(b, Archery)),
            None,
        )
        if archery is None:
            return
        eco["wood"] -= 15
        eco["meat"] -= 30
        angle = random.uniform(0, 2 * math.pi)
        self.units.append(Archer(
            archery.x + math.cos(angle) * 120,
            archery.y + math.sin(angle) * 120,
            team="blue",
        ))

    def _handle_spawn_pawn(self):
        eco = self.economy["blue"]
        if eco["meat"] < 20 or eco["pop"] >= eco["pop_cap"]:
            return
        castle = next(
            (b for b in self.buildings if b.team == "blue" and b.selected and b.alive),
            None,
        )
        if castle is None:
            return
        eco["meat"] -= 20
        angle = random.uniform(0, 2 * math.pi)
        dist  = 120
        px    = castle.x + math.cos(angle) * dist
        py    = castle.y + math.sin(angle) * dist
        pawn  = Pawn(px, py, team="blue")
        self.pawns.append(pawn)

    def _handle_spawn_lancer(self):
        eco = self.economy["blue"]
        if eco["wood"] < 45 or eco["meat"] < 10 or eco["pop"] >= eco["pop_cap"]:
            return
        barracks = next(
            (b for b in self.buildings if b.team == "blue"
             and b.selected and b.alive and isinstance(b, Barracks)),
            None,
        )
        if barracks is None:
            return
        eco["wood"] -= 45
        eco["meat"] -= 10
        angle = random.uniform(0, 2 * math.pi)
        self.units.append(Lancer(
            barracks.x + math.cos(angle) * 120,
            barracks.y + math.sin(angle) * 120,
            team="blue",
        ))

    def _handle_spawn_warrior(self):
        eco = self.economy["blue"]
        if eco["gold"] < 35 or eco["meat"] < 40 or eco["pop"] >= eco["pop_cap"]:
            return
        barracks = next(
            (b for b in self.buildings if b.team == "blue"
             and b.selected and b.alive and isinstance(b, Barracks)),
            None,
        )
        if barracks is None:
            return
        eco["gold"] -= 35
        eco["meat"] -= 40
        angle = random.uniform(0, 2 * math.pi)
        self.units.append(Warrior(
            barracks.x + math.cos(angle) * 120,
            barracks.y + math.sin(angle) * 120,
            team="blue",
        ))

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
        bp = Blueprint(building)
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
                for e in self.units + self.buildings
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
        goal_col = int(wx // TILE_SIZE)
        goal_row = int(wy // TILE_SIZE)
        all_selected = selected_combat + selected_pawns
        offsets = self._formation_offsets(len(all_selected))
        for unit, (dc, dr) in zip(all_selected, offsets):
            target = (goal_col + dc, goal_row + dr)
            if not self.map.is_walkable(*target):
                target = (goal_col, goal_row)
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
        self.camera.update(dt, self.map.pixel_width, self.map.pixel_height)

        for unit in self.units:
            new_arrows = unit.update(dt, self.map)
            self.arrows.extend(new_arrows)

        for pawn in self.pawns:
            deposit = pawn.update(dt, self.map)
            for resource_type, amount in deposit.items():
                self.economy["blue"][resource_type] += amount

        for arrow in self.arrows:
            arrow.update(dt)

        for res in self.resources:
            res.update(dt)

        self._apply_separation(dt)
        self._apply_building_collision()

        for bp in self.blueprints:
            if bp.alive and bp.progress >= bp.max_hp:
                self.buildings.append(bp.complete())

        self.units      = [u for u in self.units      if u.alive]
        self.pawns      = [p for p in self.pawns      if p.alive]
        self.arrows     = [a for a in self.arrows     if a.alive]
        self.buildings  = [b for b in self.buildings  if b.alive]
        self.blueprints = [b for b in self.blueprints if b.alive]
        self._recalc_pop()

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
        RADIUS = 40.0
        FORCE = 120.0
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
        self.map.render(self.screen, self.camera)

        # Y-sort all world objects so lower objects draw on top (painter's algorithm)
        world_objects = self.resources + self.blueprints + self.buildings + self.units + self.pawns
        world_objects.sort(key=lambda obj: obj.sort_y)
        for obj in world_objects:
            obj.render(self.screen, self.camera)

        for arrow in self.arrows:
            arrow.render(self.screen, self.camera)

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
            if task == "to_resource" and pawn._resource_node:
                target = (pawn._resource_node.x, pawn._resource_node.y)
                color = (0, 220, 255)
            elif task in ("gather",) and pawn._resource_node:
                target = (pawn._resource_node.x, pawn._resource_node.y)
                color = (0, 255, 100)
            elif task == "to_depot":
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

