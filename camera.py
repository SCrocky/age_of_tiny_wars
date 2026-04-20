import pygame


class Camera:
    PAN_SPEED = 500      # world pixels per second
    ZOOM_STEP = 0.1
    MIN_ZOOM = 0.05
    MAX_ZOOM = 3.0
    EDGE_SCROLL_MARGIN = 20  # px from screen edge that triggers scrolling

    def __init__(self, screen_width: int, screen_height: int):
        self.x = 0.0          # world-space position of the top-left of the viewport
        self.y = 0.0
        self.zoom = 1.0
        self.screen_width = screen_width
        self.screen_height = screen_height

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def update(self, dt: float, map_pixel_width: int, map_pixel_height: int):
        keys = pygame.key.get_pressed()
        mouse_x, mouse_y = pygame.mouse.get_pos()

        speed = self.PAN_SPEED / self.zoom * dt

        # Keyboard pan (arrow keys)
        if keys[pygame.K_LEFT]:
            self.x -= speed
        if keys[pygame.K_RIGHT]:
            self.x += speed
        if keys[pygame.K_UP]:
            self.y -= speed
        if keys[pygame.K_DOWN]:
            self.y += speed

        # Edge-scroll with mouse
        m = self.EDGE_SCROLL_MARGIN
        if mouse_x < m:
            self.x -= speed
        if mouse_x > self.screen_width - m:
            self.x += speed
        if mouse_y < m:
            self.y -= speed
        if mouse_y > self.screen_height - m:
            self.y += speed

        # Clamp so the viewport never leaves the map
        max_x = max(0.0, map_pixel_width - self.screen_width / self.zoom)
        max_y = max(0.0, map_pixel_height - self.screen_height / self.zoom)
        self.x = max(0.0, min(self.x, max_x))
        self.y = max(0.0, min(self.y, max_y))

    def zoom_at(self, screen_x: float, screen_y: float, direction: int):
        """Zoom in/out keeping the point under the cursor fixed in world space."""
        wx_before, wy_before = self.screen_to_world(screen_x, screen_y)

        self.zoom = max(
            self.MIN_ZOOM,
            min(self.MAX_ZOOM, self.zoom + direction * self.ZOOM_STEP)
        )

        wx_after, wy_after = self.screen_to_world(screen_x, screen_y)
        self.x += wx_before - wx_after
        self.y += wy_before - wy_after

    # ------------------------------------------------------------------
    # Coordinate conversion
    # ------------------------------------------------------------------

    def world_to_screen(self, wx: float, wy: float) -> tuple[float, float]:
        return (wx - self.x) * self.zoom, (wy - self.y) * self.zoom

    def screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        return sx / self.zoom + self.x, sy / self.zoom + self.y
