import math
import pygame
from camera import Camera
from map import TileMap, TILE_SIZE
from entities.unit import Archer
from entities.lancer import Lancer
from entities.projectile import Arrow
from systems.pathfinding import astar

DRAG_THRESHOLD = 5   # px — minimum drag distance to trigger box-select


class Game:
    MAP_COLS = 50
    MAP_ROWS = 40

    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self.w = screen.get_width()
        self.h = screen.get_height()

        self.map = TileMap(self.MAP_COLS, self.MAP_ROWS)
        self.camera = Camera(self.w, self.h)
        self.camera.x = (self.map.pixel_width  - self.w) / 2
        self.camera.y = (self.map.pixel_height - self.h) / 2

        self.font = pygame.font.SysFont(None, 22)

        self.units:   list[Archer | Lancer] = []
        self.arrows:  list[Arrow]  = []

        self._spawn_starting_units()

        # Drag-box selection state
        self._drag_start: tuple[int, int] | None = None
        self._dragging:   bool = False

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _spawn_starting_units(self):
        cx = self.map.pixel_width  // 2
        cy = self.map.pixel_height // 2

        # Player units — left side
        for dx, dy in [(-160, -40), (-80, -40), (0, -40)]:
            self.units.append(Archer(cx + dx, cy + dy, team="blue"))
        for dx, dy in [(-140, 40), (-60, 40), (20, 40)]:
            self.units.append(Lancer(cx + dx, cy + dy, team="blue"))

        # Enemy units — right side
        for dx, dy in [(200, -60), (280, -40), (360, -60)]:
            self.units.append(Archer(cx + dx, cy + dy, team="black"))
        for dx, dy in [(220, 40), (300, 60), (380, 40)]:
            self.units.append(Lancer(cx + dx, cy + dy, team="black"))

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                pygame.event.post(pygame.event.Event(pygame.QUIT))

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
                    self._handle_left_click(event.pos)
                self._drag_start = None
                self._dragging   = False

        elif event.type == pygame.MOUSEMOTION:
            if self._drag_start:
                dx = event.pos[0] - self._drag_start[0]
                dy = event.pos[1] - self._drag_start[1]
                if dx * dx + dy * dy > DRAG_THRESHOLD ** 2:
                    self._dragging = True

    # ------------------------------------------------------------------
    # Click handlers
    # ------------------------------------------------------------------

    def _handle_left_click(self, screen_pos: tuple[int, int]):
        sx, sy = screen_pos
        clicked = next((u for u in self.units
                        if u.team == "blue" and u.hit_test(sx, sy, self.camera)), None)

        mods = pygame.key.get_mods()
        if not (mods & pygame.KMOD_SHIFT):
            for u in self.units:
                u.selected = False

        if clicked:
            clicked.selected = (not clicked.selected
                                 if (mods & pygame.KMOD_SHIFT) else True)

    def _handle_box_select(self, start: tuple[int, int], end: tuple[int, int]):
        x1 = min(start[0], end[0])
        y1 = min(start[1], end[1])
        x2 = max(start[0], end[0])
        y2 = max(start[1], end[1])

        mods = pygame.key.get_mods()
        if not (mods & pygame.KMOD_SHIFT):
            for u in self.units:
                u.selected = False

        for u in self.units:
            if u.team != "blue":
                continue
            ux, uy = self.camera.world_to_screen(u.x, u.y)
            if x1 <= ux <= x2 and y1 <= uy <= y2:
                u.selected = True

    def _handle_right_click(self, screen_pos: tuple[int, int]):
        selected = [u for u in self.units if u.selected]
        if not selected:
            return

        sx, sy = screen_pos

        # Check if right-clicking on an enemy unit → attack command
        enemy = next((u for u in self.units
                      if u.team != "blue" and u.hit_test(sx, sy, self.camera)), None)
        if enemy:
            for unit in selected:
                unit.set_attack_target(enemy)
            return

        # Otherwise → move command
        wx, wy = self.camera.screen_to_world(sx, sy)
        goal_col = int(wx // TILE_SIZE)
        goal_row = int(wy // TILE_SIZE)

        offsets = self._formation_offsets(len(selected))
        for unit, (dc, dr) in zip(selected, offsets):
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

        self._apply_separation(dt)

        for arrow in self.arrows:
            arrow.update(dt)

        # Remove dead units and spent arrows
        self.units  = [u for u in self.units  if u.alive]
        self.arrows = [a for a in self.arrows if a.alive]

    def _apply_separation(self, dt: float):
        """Push overlapping units apart so they don't stack."""
        RADIUS = 40.0   # world px — personal space bubble
        FORCE  = 120.0  # world px/s — how hard they push

        for i, a in enumerate(self.units):
            fx = fy = 0.0
            for j, b in enumerate(self.units):
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
            # Apply each axis only if it stays on walkable ground
            if self.map.is_walkable(int(new_x // TILE_SIZE), int(a.y   // TILE_SIZE)):
                a.x = new_x
            if self.map.is_walkable(int(a.x   // TILE_SIZE), int(new_y // TILE_SIZE)):
                a.y = new_y

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def render(self):
        self.screen.fill((10, 20, 40))
        self.map.render(self.screen, self.camera)

        for unit in self.units:
            unit.render(self.screen, self.camera)

        for arrow in self.arrows:
            arrow.render(self.screen, self.camera)

        self._draw_drag_box()
        self._draw_hud()

    def _draw_drag_box(self):
        if not self._dragging or self._drag_start is None:
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

    def _draw_hud(self):
        blue  = sum(1 for u in self.units if u.team == "blue")
        black = sum(1 for u in self.units if u.team == "black")
        sel   = sum(1 for u in self.units if u.selected)
        lines = [
            "WASD/Arrows: pan   Scroll: zoom   Esc: quit",
            "Left-click / drag: select   Shift: multi   Right-click: move / attack",
            f"Blue: {blue}   Black: {black}   Selected: {sel}   Arrows: {len(self.arrows)}",
        ]
        for i, line in enumerate(lines):
            surf = self.font.render(line, True, (230, 230, 230))
            self.screen.blit(surf, (10, 8 + i * 20))
