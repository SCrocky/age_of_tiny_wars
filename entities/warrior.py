import math
import pygame
from entities.unit import Unit

ANIM_FPS        = 8
ATTACK_DAMAGE   = 25
ATTACK_COOLDOWN = 2.0
HIT_DELAY       = 0.5
GUARD_DURATION  = 0.5   # how long the guard animation stays visible


def _load_sheet(path: str, frame_size: int) -> list[pygame.Surface]:
    sheet = pygame.image.load(path).convert_alpha()
    count = sheet.get_width() // frame_size
    return [
        sheet.subsurface(pygame.Rect(i * frame_size, 0, frame_size, frame_size))
        for i in range(count)
    ]


class Warrior(Unit):
    """
    Slow melee unit that guards against the first hit received during
    its attack cooldown, taking only half damage from that hit.

    States
    ------
    idle    – standing still
    run     – following a path
    attack  – in melee range of target (alternates Attack1 / Attack2)
    guard   – brief visual played when a block lands
    """

    FRAME_SIZE   = 192
    DISPLAY_SIZE = 128
    MOVE_SPEED   = 80.0
    ATTACK_RANGE = 55.0

    def __init__(self, x: float, y: float, team: str = "blue"):
        super().__init__(x, y, team, max_hp=150)

        folder = f"assets/Units/{team.capitalize()} Units/Warrior"
        fs = self.FRAME_SIZE
        self._frames_idle    = _load_sheet(f"{folder}/Warrior_Idle.png",    fs)
        self._frames_run     = _load_sheet(f"{folder}/Warrior_Run.png",     fs)
        self._frames_attack  = [
            _load_sheet(f"{folder}/Warrior_Attack1.png", fs),
            _load_sheet(f"{folder}/Warrior_Attack2.png", fs),
        ]
        self._frames_guard   = _load_sheet(f"{folder}/Warrior_Guard.png",   fs)

        self._state:        str   = "idle"
        self._frame_idx:    int   = 0
        self._anim_timer:   float = 0.0
        self._attack_set:   int   = 0    # alternates 0 / 1

        self.attack_range: float = self.ATTACK_RANGE
        self._hit_timer:   float = 0.0

        self._guard_ready:    bool  = True    # one block available per attack cycle
        self._guard_timer:    float = 0.0     # drives guard anim display

    # ------------------------------------------------------------------
    # Damage interception
    # ------------------------------------------------------------------

    def receive_melee_hit(self, attacker):
        dx = attacker.x - self.x
        if abs(dx) > 1:
            self._facing_right = dx > 0

    def take_damage(self, amount: int, is_melee: bool = False):
        if is_melee and self._guard_ready:
            amount = max(1, amount // 2)
            self._guard_ready = False
            self._guard_timer = GUARD_DURATION
            self._frame_idx   = 0
        super().take_damage(amount)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, dt: float, tile_map=None) -> list:
        self._time        += dt
        self._guard_timer  = max(0.0, self._guard_timer - dt)

        if self.attack_target is not None:
            if not self.attack_target.alive:
                self.attack_target = None
            else:
                if self._dist_to_target() <= self.attack_range:
                    self.path   = []
                    self._state = "attack"
                    self._tick_melee(dt)
                else:
                    self._state     = "run"
                    self._hit_timer = 0.0
                    if tile_map is not None:
                        self._chase_timer -= dt
                        if self._chase_timer <= 0:
                            self._chase_timer = self.CHASE_INTERVAL
                            self._repath_to_target(tile_map)
                    self._move_along_path(dt)

        elif self.path:
            self._state = "run"
            self._move_along_path(dt)
        else:
            self._state = "idle"

        self._tick_animation(dt)
        return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _tick_melee(self, dt: float):
        if self._time - self._last_shot_time < ATTACK_COOLDOWN:
            return

        if self._hit_timer == 0.0:
            self._frame_idx = 0

        dx = self.attack_target.x - self.x
        if abs(dx) > 1:
            self._facing_right = dx > 0

        self._hit_timer += dt
        if self._hit_timer >= HIT_DELAY:
            self.attack_target.take_damage(ATTACK_DAMAGE, is_melee=True)
            self.attack_target.receive_melee_hit(self)
            self._last_shot_time = self._time
            self._hit_timer      = 0.0
            self._guard_ready    = True
            self._attack_set     = 1 - self._attack_set
            self._frame_idx      = 0

    def _tick_animation(self, dt: float):
        self._anim_timer += dt
        if self._anim_timer >= 1.0 / ANIM_FPS:
            self._anim_timer -= 1.0 / ANIM_FPS
            frames = self._current_frames()
            if self._state == "attack" and self._frame_idx >= len(frames) - 1:
                pass  # hold last frame until next swing resets to 0
            else:
                self._frame_idx = (self._frame_idx + 1) % len(frames)

    def _current_frames(self) -> list:
        if self._guard_timer > 0:
            return self._frames_guard
        if self._state == "attack":
            if self._time - self._last_shot_time < ATTACK_COOLDOWN:
                return self._frames_idle
            return self._frames_attack[self._attack_set]
        if self._state == "run":
            return self._frames_run
        return self._frames_idle

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def render(self, surface: pygame.Surface, camera):
        frames = self._current_frames()
        frame  = frames[self._frame_idx % len(frames)]

        size   = max(1, int(self.DISPLAY_SIZE * camera.zoom))
        scaled = pygame.transform.scale(frame, (size, size))
        if not self._facing_right:
            scaled = pygame.transform.flip(scaled, True, False)

        sx, sy = camera.world_to_screen(self.x, self.y)
        surface.blit(scaled, (int(sx - size / 2), int(sy - size / 2)))

        if self.selected:
            r = max(2, int(22 * camera.zoom))
            pygame.draw.circle(surface, (255, 220, 0), (int(sx), int(sy)), r, 2)

        self.draw_health_bar(surface, camera)
