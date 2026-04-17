import math
import random
import pygame
from camera import Camera
from map import TileMap, TILE_SIZE
from entities.unit import Archer
from entities.lancer import Lancer
from entities.pawn import Pawn
from entities.building import Castle
from entities.resource import GoldNode, WoodNode, MeatNode
from entities.projectile import Arrow
from systems.pathfinding import astar

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

        self.units: list = []
        self.pawns: list[Pawn] = []
        self.arrows: list[Arrow] = []
        self.buildings: list[Castle] = []
        self.resources: list = []

        # Economy: resource counts per team
        self.economy: dict[str, dict[str, int]] = {
            "blue": {"gold": 0, "wood": 0, "meat": 0},
            "black": {"gold": 0, "wood": 0, "meat": 0},
        }

        self._spawn_world()

        self._drag_start: tuple[int, int] | None = None
        self._dragging: bool = False
        self.debug: bool = False

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _spawn_world(self):
        cx = self.map.pixel_width // 2
        cy = self.map.pixel_height // 2

        # --- Castles ---
        blue_castle = Castle(cx - 400, cy, team="blue")
        black_castle = Castle(cx + 400, cy, team="black")
        self.buildings = [blue_castle, black_castle]

        # Clear water then block the castle footprint so units can't walk through it
        for castle in self.buildings:
            self.map.clear_area(castle.x, castle.y, tile_radius=6)
            self.map.block_area(castle.x, castle.y, half_w=2, half_h=1)

        # --- Player combat units (spawned to the right of the blue castle) ---
        for dx, dy in [(-100, -80), (-20, -80), (60, -80)]:
            self.units.append(Archer(cx + dx, cy + dy, team="blue"))
        for dx, dy in [(-60, 80), (20, 80)]:
            self.units.append(Lancer(cx + dx, cy + dy, team="blue"))

        # --- Enemy combat units (spawned to the left of the black castle) ---
        for dx, dy in [(100, -80), (20, -80), (-60, -80)]:
            self.units.append(Archer(cx + dx, cy + dy, team="black"))
        for dx, dy in [(60, 80), (-20, 80)]:
            self.units.append(Lancer(cx + dx, cy + dy, team="black"))

        # --- Player pawns (to the left of the blue castle, outside its footprint) ---
        for dx, dy in [(-580, -60), (-620, 0), (-580, 60)]:
            self.pawns.append(Pawn(cx + dx, cy + dy, team="blue"))

        # --- Resource nodes (shared map, accessible to both sides) ---
        rng = random.Random(7)
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

        for _ in range(5):
            x, y = rand_grass_pos()
            self.resources.append(GoldNode(x, y))
        for i in range(6):
            x, y = rand_grass_pos()
            self.resources.append(WoodNode(x, y, variant=i))
        for _ in range(4):
            x, y = rand_grass_pos()
            self.resources.append(MeatNode(x, y))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _all_selectable(self):
        return self.units + self.pawns

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
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
        for u in self._all_selectable():
            if u.team != "blue":
                continue
            ux, uy = self.camera.world_to_screen(u.x, u.y)
            if x1 <= ux <= x2 and y1 <= uy <= y2:
                u.selected = True

    def _handle_right_click(self, screen_pos):
        sx, sy = screen_pos
        wx, wy = self.camera.screen_to_world(sx, sy)

        selected_combat = [u for u in self.units if u.selected]
        selected_pawns = [p for p in self.pawns if p.selected]

        # Right-click on enemy → attack (combat units only)
        enemy = next(
            (
                u
                for u in self.units
                if u.team != "blue" and u.hit_test(sx, sy, self.camera)
            ),
            None,
        )
        if enemy and selected_combat:
            for unit in selected_combat:
                unit.set_attack_target(enemy)
            return

        # Right-click on a resource node → gather (pawns only)
        friendly_depots = [b for b in self.buildings if b.team == "blue"]
        if friendly_depots and selected_pawns:
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
                    pawn.assign_gather(resource, friendly_depots)
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

    def update(self, dt: float):
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

        self.units = [u for u in self.units if u.alive]
        self.pawns = [p for p in self.pawns if p.alive]
        self.arrows = [a for a in self.arrows if a.alive]

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
        world_objects = self.resources + self.buildings + self.units + self.pawns
        world_objects.sort(key=lambda obj: obj.y)
        for obj in world_objects:
            obj.render(self.screen, self.camera)

        for arrow in self.arrows:
            arrow.render(self.screen, self.camera)

        self._draw_drag_box()
        if self.debug:
            self._draw_debug()
        self._draw_hud()

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

            # Depot deposit radius rings
            for depot in pawn._depots:
                dx, dy = self.camera.world_to_screen(depot.x, depot.y)
                r = int(depot.DEPOSIT_RADIUS * self.camera.zoom)
                pygame.draw.circle(self.screen, (255, 120, 0), (int(dx), int(dy)), r, 1)

    def _draw_hud(self):
        eco = self.economy["blue"]
        blue = sum(1 for u in self.units if u.team == "blue")
        black = sum(1 for u in self.units if u.team == "black")
        sel = sum(1 for u in self._all_selectable() if u.selected)

        lines = [
            "WASD/Arrows: pan   Scroll: zoom   D: debug   Esc: quit",
            "Left/drag: select   Shift: multi   Right-click: move / attack / gather",
            f"Blue: {blue}  Black: {black}  Pawns: {len(self.pawns)}  Selected: {sel}",
            f"Gold: {eco['gold']}   Wood: {eco['wood']}   Meat: {eco['meat']}",
        ]
        for i, line in enumerate(lines):
            surf = self.font.render(line, True, (230, 230, 230))
            self.screen.blit(surf, (10, 8 + i * 20))
