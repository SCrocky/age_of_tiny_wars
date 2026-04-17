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

    def gather(self, amount: int) -> int:
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
    max_amount    = 300
    DISPLAY_SIZE  = 96    # world px

    def __init__(self, x: float, y: float):
        super().__init__(x, y)
        self._surf = pygame.image.load(
            "assets/Terrain/Resources/Gold/Gold Resource/Gold_Resource.png"
        ).convert_alpha()

    def render(self, surface: pygame.Surface, camera):
        if self.depleted:
            return
        size = max(1, int(self.DISPLAY_SIZE * camera.zoom))
        scaled = pygame.transform.scale(self._surf, (size, size))
        sx, sy = camera.world_to_screen(self.x, self.y)
        surface.blit(scaled, (int(sx - size / 2), int(sy - size / 2)))
        self._draw_amount_bar(surface, camera)

    def _draw_amount_bar(self, surface, camera):
        sx, sy = camera.world_to_screen(self.x, self.y)
        bw = int(50 * camera.zoom)
        bh = max(3, int(4 * camera.zoom))
        bx = int(sx - bw / 2)
        by = int(sy - self.DISPLAY_SIZE * camera.zoom / 2 - bh - 2)
        pygame.draw.rect(surface, (60, 60, 0),   (bx, by, bw, bh))
        fill = int(bw * self.amount / self.max_amount)
        pygame.draw.rect(surface, (220, 180, 0), (bx, by, fill, bh))
        pygame.draw.rect(surface, (0, 0, 0),     (bx, by, bw, bh), 1)


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


class MeatNode(ResourceNode):
    resource_type = "meat"
    max_amount    = 150
    FRAME_SIZE    = 128
    DISPLAY_SIZE  = 80

    def __init__(self, x: float, y: float):
        super().__init__(x, y)
        self._idle_frames = _load_sheet(
            "assets/Terrain/Resources/Meat/Sheep/Sheep_Idle.png",
            self.FRAME_SIZE,
        )

    def _frame_count(self) -> int:
        return len(self._idle_frames)

    def render(self, surface: pygame.Surface, camera):
        if self.depleted:
            return
        frame = self._idle_frames[self._frame_idx % len(self._idle_frames)]
        size = max(1, int(self.DISPLAY_SIZE * camera.zoom))
        scaled = pygame.transform.scale(frame, (size, size))
        sx, sy = camera.world_to_screen(self.x, self.y)
        surface.blit(scaled, (int(sx - size / 2), int(sy - size / 2)))
