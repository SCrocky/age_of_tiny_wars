import math
import random
import pygame

ANIM_FPS = 6
HIT_RADIUS = 48.0   # world px for click detection


def _load_sheet(path: str, frame_w: int) -> list[pygame.Surface]:
    sheet = pygame.image.load(path).convert_alpha()
    frame_h = sheet.get_height()
    count = sheet.get_width() // frame_w
    return [
        sheet.subsurface(pygame.Rect(i * frame_w, 0, frame_w, frame_h))
        for i in range(count)
    ]


class ResourceNode:
    """Base class for gatherable resource nodes."""

    resource_type: str = ""    # 'gold' | 'wood' | 'meat'
    max_amount:    int = 200

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y
        self.amount  = self.max_amount
        self._frame_idx   = 0
        self._anim_timer  = 0.0

    @property
    def depleted(self) -> bool:
        return self.amount <= 0

    @property
    def sort_y(self) -> float:
        return self.y

    def gather(self, amount: int, gatherer=None) -> int:
        """Remove up to `amount` from this node; returns what was actually taken."""
        taken = min(amount, self.amount)
        self.amount -= taken
        return taken

    def update(self, dt: float):
        self._anim_timer += dt
        if self._anim_timer >= 1.0 / ANIM_FPS:
            self._anim_timer -= 1.0 / ANIM_FPS
            self._frame_idx = (self._frame_idx + 1) % self._frame_count()

    def _frame_count(self) -> int:
        return 1

    def render(self, surface: pygame.Surface, camera):
        raise NotImplementedError

    def hit_test(self, sx: float, sy: float, camera) -> bool:
        ux, uy = camera.world_to_screen(self.x, self.y)
        r = HIT_RADIUS * camera.zoom
        return (sx - ux) ** 2 + (sy - uy) ** 2 <= r * r


# ---------------------------------------------------------------------------

class GoldNode(ResourceNode):
    resource_type = "gold"
    FRAME_W       = 128
    DISPLAY_SIZE  = 96

    def __init__(self, x: float, y: float, variant: int = 1):
        self.max_amount = variant * 100
        super().__init__(x, y)
        n = max(1, min(6, variant))
        self._frames = _load_sheet(
            f"assets/Terrain/Resources/Gold/Gold Stones/Gold Stone {n}_Highlight.png",
            self.FRAME_W,
        )

    def _frame_count(self) -> int:
        return len(self._frames)

    def render(self, surface: pygame.Surface, camera):
        if self.depleted:
            return
        frame = self._frames[self._frame_idx % len(self._frames)]
        size = max(1, int(self.DISPLAY_SIZE * camera.zoom))
        scaled = pygame.transform.scale(frame, (size, size))
        sx, sy = camera.world_to_screen(self.x, self.y)
        surface.blit(scaled, (int(sx - size / 2), int(sy - size / 2)))


class WoodNode(ResourceNode):
    resource_type = "wood"
    max_amount    = 250
    FRAME_W       = 192   # 1536px sheet ÷ 8 frames
    DISPLAY_SIZE  = 112

    def __init__(self, x: float, y: float, variant: int = 0):
        super().__init__(x, y)
        n = (variant % 4) + 1
        self._frames = _load_sheet(
            f"assets/Terrain/Resources/Wood/Trees/Tree{n}.png",
            self.FRAME_W,
        )
        self._stump = pygame.image.load(
            f"assets/Terrain/Resources/Wood/Trees/Stump {n}.png"
        ).convert_alpha()

    def _frame_count(self) -> int:
        return len(self._frames)

    def render(self, surface: pygame.Surface, camera):
        sx, sy = camera.world_to_screen(self.x, self.y)
        size = max(1, int(self.DISPLAY_SIZE * camera.zoom))
        if self.depleted:
            sw = max(1, int(size * 192 / 256))
            scaled = pygame.transform.scale(self._stump, (sw, size))
            surface.blit(scaled, (int(sx - sw / 2), int(sy - size / 2)))
            return
        frame = self._frames[self._frame_idx % len(self._frames)]
        scaled = pygame.transform.scale(frame, (size, size))
        surface.blit(scaled, (int(sx - size / 2), int(sy - size / 2)))


_FLEE_SPEED      = 130.0
_WANDER_SPEED    = 50.0
_FLEE_DISTANCE   = 180.0
_WANDER_DISTANCE = 100.0
_IDLE_MIN        = 2.0
_IDLE_MAX        = 5.0
_EAT_CYCLES      = 2   # full eat-grass animations per idle action


class MeatNode(ResourceNode):
    resource_type = "meat"
    max_amount    = 150
    FRAME_SIZE    = 128
    DISPLAY_SIZE  = 80

    def __init__(self, x: float, y: float):
        super().__init__(x, y)
        fs = self.FRAME_SIZE
        self._frames_idle  = _load_sheet("assets/Terrain/Resources/Meat/Sheep/Sheep_Idle.png",  fs)
        self._frames_grass = _load_sheet("assets/Terrain/Resources/Meat/Sheep/Sheep_Grass.png", fs)
        self._frames_move  = _load_sheet("assets/Terrain/Resources/Meat/Sheep/Sheep_Move.png",  fs)

        self._sheep_state:    str   = "idle"
        self._idle_timer:     float = random.uniform(_IDLE_MIN, _IDLE_MAX)
        self._eat_cycles_left: int  = 0
        self._target_x:       float = x
        self._target_y:       float = y
        self._speed:          float = 0.0
        self._facing_right:   bool  = True
        self._rng = random.Random(int(x * 7 + y * 13))

    # ------------------------------------------------------------------

    def _active_frames(self) -> list:
        if self._sheep_state in ("move", "flee"):
            return self._frames_move
        if self._sheep_state == "eat_grass":
            return self._frames_grass
        return self._frames_idle

    def _frame_count(self) -> int:
        return len(self._active_frames())

    def gather(self, amount: int, gatherer=None) -> int:
        taken = super().gather(amount)
        if taken > 0 and gatherer is not None:
            self.receive_melee_hit(gatherer)
        return taken

    def receive_melee_hit(self, attacker):
        dx = self.x - attacker.x
        dy = self.y - attacker.y
        dist = math.hypot(dx, dy) or 1
        self._target_x = self.x + dx / dist * _FLEE_DISTANCE
        self._target_y = self.y + dy / dist * _FLEE_DISTANCE
        self._speed = _FLEE_SPEED
        self._sheep_state = "flee"
        self._facing_right = dx >= 0
        self._frame_idx = 0

    # ------------------------------------------------------------------

    def update(self, dt: float, tile_map=None):
        if self._sheep_state == "idle":
            self._idle_timer -= dt
            if self._idle_timer <= 0:
                if self._rng.random() < 0.5:
                    self._sheep_state     = "eat_grass"
                    self._eat_cycles_left = _EAT_CYCLES
                    self._frame_idx       = 0
                else:
                    angle = self._rng.uniform(0, 2 * math.pi)
                    self._target_x    = self.x + math.cos(angle) * _WANDER_DISTANCE
                    self._target_y    = self.y + math.sin(angle) * _WANDER_DISTANCE
                    self._speed       = _WANDER_SPEED
                    self._facing_right = math.cos(angle) >= 0
                    self._sheep_state  = "move"
                    self._frame_idx    = 0

        elif self._sheep_state in ("move", "flee"):
            dx = self._target_x - self.x
            dy = self._target_y - self.y
            dist = math.hypot(dx, dy)
            step = self._speed * dt
            if dist <= step:
                self.x, self.y    = self._target_x, self._target_y
                self._sheep_state = "idle"
                self._idle_timer  = self._rng.uniform(_IDLE_MIN, _IDLE_MAX)
                self._frame_idx   = 0
            else:
                self.x += dx / dist * step
                self.y += dy / dist * step
                self._facing_right = dx >= 0

        # Animate
        self._anim_timer += dt
        if self._anim_timer >= 1.0 / ANIM_FPS:
            self._anim_timer -= 1.0 / ANIM_FPS
            frames = self._active_frames()
            self._frame_idx += 1
            if self._frame_idx >= len(frames):
                self._frame_idx = 0
                if self._sheep_state == "eat_grass":
                    self._eat_cycles_left -= 1
                    if self._eat_cycles_left <= 0:
                        self._sheep_state = "idle"
                        self._idle_timer  = self._rng.uniform(_IDLE_MIN, _IDLE_MAX)

    # ------------------------------------------------------------------

    def render(self, surface: pygame.Surface, camera):
        if self.depleted:
            return
        frames = self._active_frames()
        frame  = frames[self._frame_idx % len(frames)]
        size   = max(1, int(self.DISPLAY_SIZE * camera.zoom))
        scaled = pygame.transform.scale(frame, (size, size))
        if not self._facing_right:
            scaled = pygame.transform.flip(scaled, True, False)
        sx, sy = camera.world_to_screen(self.x, self.y)
        surface.blit(scaled, (int(sx - size / 2), int(sy - size / 2)))
