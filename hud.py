import pygame
import assets

_UI = "assets/UI Elements/UI Elements"

_AVATAR_IDX: dict[tuple[str, str], int] = {
    ("Warrior",  "blue"):  1,
    ("Lancer",   "blue"):  2,
    ("Archer",   "blue"):  3,
    ("Pawn",     "blue"):  5,
    ("Castle",   "blue"):  5,
    ("Archery",  "blue"):  3,
    ("Barracks", "blue"):  1,
    ("Warrior",  "black"): 21,
    ("Lancer",   "black"): 22,
    ("Archer",   "black"): 23,
    ("Pawn",     "black"): 25,
    ("Castle",   "black"): 25,
    ("Archery",  "black"): 23,
    ("Barracks", "black"): 21,
}

PAWN_COST    = {"meat": 20}
ARCHER_COST  = {"wood": 15, "meat": 30}
LANCER_COST  = {"wood": 45, "meat": 10}
WARRIOR_COST = {"gold": 35, "meat": 40}

BUTTON_SIZE = 72   # fixed size for all production buttons

# Production buttons per building type: list of (avatar_unit_key, costs, action)
_PRODUCTION: dict[str, list[tuple[str, dict, str]]] = {
    "Castle":   [("Pawn",    PAWN_COST,    "spawn_pawn")],
    "Archery":  [("Archer",  ARCHER_COST,  "spawn_archer")],
    "Barracks": [("Lancer",  LANCER_COST,  "spawn_lancer"),
                 ("Warrior", WARRIOR_COST, "spawn_warrior")],
}


class HUD:
    CORNER  = 16
    PAD     = 8
    ICON_SZ = 28

    def __init__(self, sw: int, sh: int):
        self.sw = sw
        self.sh = sh
        self._font    = pygame.font.SysFont(None, 22)
        self._font_md = pygame.font.SysFont(None, 26)
        self._avatars: dict[int, pygame.Surface] = {}
        self._buttons: list[tuple[pygame.Rect, str]] = []
        self._load()

    # ------------------------------------------------------------------
    # Asset loading
    # ------------------------------------------------------------------

    def _load(self):
        raw_icons = {
            "gold": assets.load_image(f"{_UI}/Icons/Icon_03.png").convert_alpha(),
            "wood": assets.load_image(f"{_UI}/Icons/Icon_02.png").convert_alpha(),
            "meat": assets.load_image(f"{_UI}/Icons/Icon_04.png").convert_alpha(),
            "pop":  assets.load_image(f"{_UI}/Icons/Icon_05.png").convert_alpha(),
        }
        # Pre-scale to the two sizes used at runtime so transform.scale isn't called per frame
        s = self.ICON_SZ
        self._icons    = {k: pygame.transform.scale(v, (s, s))   for k, v in raw_icons.items()}
        self._icons_sm = {k: pygame.transform.scale(v, (14, 14)) for k, v in raw_icons.items()}

        # Panel background: stretch WoodTable_Slots.png to any size
        self._panel_bg = assets.load_image(
            f"{_UI}/Wood Table/WoodTable_Slots.png"
        ).convert_alpha()
        self._panel_cache: dict[tuple[int, int], pygame.Surface] = {}

        # HP bar: 3-part — caps at natural width, middle stretched
        base   = assets.load_image(f"{_UI}/Bars/BigBar_Base.png").convert_alpha()
        bw, bh = base.get_size()
        cap    = bw // 5
        self._bar_h     = bh
        self._bar_cap   = cap
        self._bar_left  = base.subsurface(pygame.Rect(0,       0, cap, bh)).copy()
        self._bar_mid   = base.subsurface(pygame.Rect(cap*2,     0, cap, bh)).copy()
        self._bar_right = base.subsurface(pygame.Rect(cap * 4, 0, cap, bh)).copy()
        self._bar_fill  = assets.load_image(f"{_UI}/Bars/BigBar_Fill.png").convert_alpha()
        self._fill_h    = self._bar_fill.get_height()

        btn_reg_raw = assets.load_image(
            f"{_UI}/Buttons/SmallBlueSquareButton_Regular.png"
        ).convert_alpha()
        btn_prs_raw = assets.load_image(
            f"{_UI}/Buttons/SmallBlueSquareButton_Pressed.png"
        ).convert_alpha()
        # Pre-scale buttons to the fixed BUTTON_SIZE used at runtime
        self._btn_regular = pygame.transform.scale(btn_reg_raw, (BUTTON_SIZE, BUTTON_SIZE))
        self._btn_pressed = pygame.transform.scale(btn_prs_raw, (BUTTON_SIZE, BUTTON_SIZE))
        self._btn_pressed.set_alpha(160)

        icon_size = int(BUTTON_SIZE * 0.55)
        raw_build = {
            "Archery":  assets.load_image("assets/Buildings/Blue Buildings/Archery.png").convert_alpha(),
            "Barracks": assets.load_image("assets/Buildings/Blue Buildings/Barracks.png").convert_alpha(),
            "House":    assets.load_image("assets/Buildings/Blue Buildings/House1.png").convert_alpha(),
        }
        self._build_icons: dict[str, pygame.Surface] = {
            k: pygame.transform.scale(v, (icon_size/2, icon_size/2)) for k, v in raw_build.items()
        }

    def _get_avatar(self, n: int) -> pygame.Surface:
        if n not in self._avatars:
            self._avatars[n] = assets.load_image(
                f"{_UI}/Human Avatars/Avatars_{n:02d}.png"
            ).convert_alpha()
        return self._avatars[n]

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def _draw_panel(self, surface: pygame.Surface, x: int, y: int, w: int, h: int):
        key = (max(1, w), max(1, h))
        if key not in self._panel_cache:
            self._panel_cache[key] = pygame.transform.scale(self._panel_bg, key)
        surface.blit(self._panel_cache[key], (int(x), int(y)))

    def _draw_hp_bar(self, surface: pygame.Surface, x: int, y: int, w: int,
                     hp: int, max_hp: int):
        bh  = self._bar_h
        cap = self._bar_cap
        # Caps at natural width; middle stretched to fill the gap
        surface.blit(self._bar_left,  (x,           y))
        surface.blit(self._bar_right, (x + w - cap, y))
        mid_w = max(1, w - cap * 2)
        surface.blit(pygame.transform.scale(self._bar_mid, (mid_w, bh)), (x + cap, y))
        # Fill overlay
        ratio  = max(0.0, min(1.0, hp / max(1, max_hp)))
        inner  = max(1, w - cap * 2)
        fill_w = int(inner * ratio)
        fh     = self._fill_h
        fy     = y + (bh - fh) // 2
        if fill_w > 0:
            surface.blit(
                pygame.transform.scale(self._bar_fill, (fill_w, fh)),
                (x + cap, fy),
            )

    def _can_afford(self, eco: dict, costs: dict) -> bool:
        return all(eco.get(k, 0) >= v for k, v in costs.items())

    def _draw_button(self, surface: pygame.Surface, rect: pygame.Rect,
                     icon: pygame.Surface, costs: dict[str, int],
                     affordable: bool, action: str):
        """Draw a square button with a unit icon and per-resource cost row."""
        # Buttons are always BUTTON_SIZE; pre-scaled sprites are used directly
        surface.blit(self._btn_regular if affordable else self._btn_pressed, rect.topleft)

        # Unit icon (upper area) — already pre-scaled to int(BUTTON_SIZE * 0.55)
        icon_size = icon.get_width()

        surface.blit(icon, (
            rect.x + (rect.w - icon_size) // 2,
            rect.y + 4,
        ))

        # Cost row — small resource icon + number per entry
        col    = (255, 235, 180) if affordable else (160, 120, 100)
        items  = list(costs.items())
        item_w = 14 + 2 + self._font.size("99")[0] + 4
        row_w  = len(items) * item_w - 4
        cx     = rect.x + (rect.w - row_w) // 2
        cy     = rect.bottom - 16
        for res, amount in items:
            surface.blit(self._icons_sm[res], (cx, cy))
            num = self._font.render(str(amount), True, col)
            surface.blit(num, (cx + 16, cy + 1))
            cx += item_w

        self._buttons.append((rect, action))

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def draw(self, surface: pygame.Surface, economy: dict, all_entities: list,
             player_team: str = "blue"):
        self._buttons = []
        self._draw_resources(surface, economy[player_team])
        selected = [e for e in all_entities
                    if e.selected and getattr(e, "team", None) == player_team]
        if selected:
            self._draw_selection(surface, selected, economy[player_team])

    def handle_click(self, mx: int, my: int) -> str | None:
        """Return the action string of the button clicked, or None."""
        for rect, action in self._buttons:
            if rect.collidepoint(mx, my):
                return action
        return None

    # ------------------------------------------------------------------
    # Resource panel (top-left)
    # ------------------------------------------------------------------

    def _draw_resources(self, surface: pygame.Surface, eco: dict):
        s     = self.ICON_SZ
        pad   = self.PAD
        c     = self.CORNER
        row_h = s + pad
        pw    = 160
        ph    = row_h * 4 + c + pad
        self._draw_panel(surface, pad, pad, pw, ph)
        for i, key in enumerate(("gold", "wood", "meat")):
            rx  = pad + c
            ry  = pad + c + i * row_h
            surface.blit(self._icons[key], (rx, ry))
            txt = self._font.render(str(eco[key]), True, (255, 235, 180))
            surface.blit(txt, (rx + s + 6, ry + (s - txt.get_height()) // 2))
        # Population row
        rx  = pad + c
        ry  = pad + c + 3 * row_h
        surface.blit(self._icons["pop"], (rx, ry))
        pop_txt = f"{eco.get('pop', 0)}/{eco.get('pop_cap', 0)}"
        col  = (200, 80, 80) if eco.get('pop', 0) >= eco.get('pop_cap', 1) else (255, 235, 180)
        txt  = self._font.render(pop_txt, True, col)
        surface.blit(txt, (rx + s + 6, ry + (s - txt.get_height()) // 2))

    # ------------------------------------------------------------------
    # Selection panel (bottom-centre)
    # ------------------------------------------------------------------

    def _draw_selection(self, surface: pygame.Surface, selected: list, eco: dict):
        from entities.blueprint import BUILDABLE
        pad      = self.PAD
        ph_info  = 116
        has_pawn = any(type(e).__name__ == "Pawn" for e in selected)
        ph_build = BUTTON_SIZE + pad * 2 if has_pawn else 0
        ph       = ph_info + ph_build
        pw       = min(self.sw - 40, 640)
        px       = (self.sw - pw) // 2
        py       = self.sh - ph - pad
        self._draw_panel(surface, px, py, pw, ph)
        if len(selected) == 1:
            self._draw_single(surface, selected[0], px, py, pw, ph_info, eco)
        else:
            self._draw_multi(surface, selected, px, py, pw, ph_info)
        if has_pawn:
            self._draw_build_row(surface, px, py + ph_info, pw, eco, BUILDABLE)

    def _draw_build_row(self, surface: pygame.Surface, px: int, py: int, pw: int,
                        eco: dict, buildable: dict):
        pad     = self.PAD
        names   = list(buildable.keys())
        total_w = len(names) * BUTTON_SIZE + (len(names) - 1) * pad
        start_x = px + (pw - total_w) // 2
        by      = py + pad
        for i, name in enumerate(names):
            _, costs = buildable[name]
            bx   = start_x + i * (BUTTON_SIZE + pad)
            rect = pygame.Rect(bx, by, BUTTON_SIZE, BUTTON_SIZE)
            self._draw_button(
                surface, rect,
                icon       = self._build_icons[name],
                costs      = costs,
                affordable = self._can_afford(eco, costs),
                action     = f"build_{name.lower()}",
            )

    def _draw_single(self, surface: pygame.Surface, ent, px, py, pw, ph, eco: dict):
        pad = self.PAD
        c   = self.CORNER
        cls_name = type(ent).__name__
        prod     = _PRODUCTION.get(cls_name, [])
        n_btns   = len(prod)
        btn_col_w = (n_btns * BUTTON_SIZE + (n_btns - 1) * pad + pad * 2) if n_btns else 0

        # Avatar
        av_size = ph - c - pad * 3
        av_idx  = _AVATAR_IDX.get((type(ent).__name__, ent.team), 4)
        av      = pygame.transform.scale(self._get_avatar(av_idx), (av_size, av_size))
        ax, ay  = px + c + pad, py + c
        surface.blit(av, (ax, ay))

        # Name + HP bar
        tx = ax + av_size + pad * 2
        ty = ay
        name_surf = self._font_md.render(type(ent).__name__, True, (255, 235, 180))
        surface.blit(name_surf, (tx, ty))

        bar_w = pw - (tx - px) - c - pad * 2 - btn_col_w
        bar_y = ty + name_surf.get_height() + 4
        self._draw_hp_bar(surface, tx, bar_y, bar_w, ent.hp, ent.max_hp)
        hp_txt = self._font.render(f"{ent.hp} / {ent.max_hp}", True, (200, 200, 200))
        surface.blit(hp_txt, (tx, bar_y + self._bar_h + 4))

        # Production buttons (right-aligned, one per entry in _PRODUCTION)
        if prod:
            total_w = n_btns * BUTTON_SIZE + (n_btns - 1) * pad
            start_x = px + pw - c - pad - total_w
            by      = py + (ph - BUTTON_SIZE) // 2
            for i, (unit_key, costs, action) in enumerate(prod):
                av_idx = _AVATAR_IDX.get((unit_key, ent.team), 4)
                bx     = start_x + i * (BUTTON_SIZE + pad)
                rect   = pygame.Rect(bx, by, BUTTON_SIZE, BUTTON_SIZE)
                self._draw_button(
                    surface, rect,
                    icon       = pygame.transform.scale(self._get_avatar(av_idx), (BUTTON_SIZE, BUTTON_SIZE)),
                    costs      = costs,
                    affordable = self._can_afford(eco, costs),
                    action     = action,
                )

    def _draw_multi(self, surface: pygame.Surface, selected: list, px, py, pw, ph):
        pad      = self.PAD
        c        = self.CORNER
        av_size  = ph - c - pad * 3
        max_show = max(1, (pw - c * 2 - pad) // (av_size + pad))
        for i, ent in enumerate(selected[:max_show]):
            av_idx = _AVATAR_IDX.get((type(ent).__name__, ent.team), 4)
            av     = pygame.transform.scale(self._get_avatar(av_idx), (av_size, av_size))
            ax     = px + c + pad + i * (av_size + pad)
            ay     = py + c
            surface.blit(av, (ax, ay))
            ratio = max(0, ent.hp) / max(1, ent.max_hp)
            col   = (50, 200, 80) if ratio > 0.5 else (220, 180, 0) if ratio > 0.25 else (200, 50, 50)
            pygame.draw.rect(surface, col, (ax, ay + av_size + 2, av_size, 4))
        if len(selected) > max_show:
            more = self._font.render(f"+{len(selected) - max_show}", True, (200, 200, 200))
            surface.blit(more, (px + pw - c - more.get_width() - pad,
                                py + (ph - more.get_height()) // 2))
