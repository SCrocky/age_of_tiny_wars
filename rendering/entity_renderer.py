from __future__ import annotations
import pygame
from render_cache import get_scaled, get_scaled_rotated, get_font

# ---------------------------------------------------------------------------
# Surface caches — keyed by sprite_key string.
# Surfaces are loaded on first use; no Pygame state needed at import time.
# ---------------------------------------------------------------------------

_building_surfs: dict[str, pygame.Surface] = {}

# Maps "building/{type}/{team}" → asset path.
# House variants (house1/house2/house3) are handled by the loader below.
_BUILDING_FILENAMES: dict[str, str] = {
    "archery":  "Archery.png",
    "barracks": "Barracks.png",
    "castle":   "Castle.png",
    "house1":   "House1.png",
    "house2":   "House2.png",
    "house3":   "House3.png",
}


def _load_building_surf(sprite_key: str) -> pygame.Surface:
    """Load and cache a building surface from its sprite key."""
    surf = _building_surfs.get(sprite_key)
    if surf is None:
        # sprite_key format: "building/{type}/{team}"
        _, btype, team = sprite_key.split("/")
        filename = _BUILDING_FILENAMES[btype]
        path = f"assets/Buildings/{team.capitalize()} Buildings/{filename}"
        surf = pygame.image.load(path).convert_alpha()
        _building_surfs[sprite_key] = surf
    return surf


# ---------------------------------------------------------------------------
# Health bar
# ---------------------------------------------------------------------------

def draw_health_bar(
    entity,
    surface: pygame.Surface,
    camera,
    width: int = 40,
    force: bool = False,
) -> None:
    """Render a health bar above *entity*. Visible when selected, damaged, or forced."""
    if not force and not entity.selected and entity.hp == entity.max_hp:
        return

    sx, sy = camera.world_to_screen(entity.x, entity.y)
    bar_w = int(width * camera.zoom)
    bar_h = max(3, int(4 * camera.zoom))
    bx = int(sx - bar_w / 2)
    by = int(sy - int(36 * camera.zoom))

    pygame.draw.rect(surface, (80, 0, 0),   (bx, by, bar_w, bar_h))
    fill = int(bar_w * entity.hp / entity.max_hp)
    pygame.draw.rect(surface, (0, 200, 60), (bx, by, fill,  bar_h))
    pygame.draw.rect(surface, (0, 0, 0),    (bx, by, bar_w, bar_h), 1)


# ---------------------------------------------------------------------------
# Building renderer
# ---------------------------------------------------------------------------

def render_building(building, surface: pygame.Surface, camera) -> None:
    if not building.alive:
        return
    surf = _load_building_surf(building.sprite_key)
    w = max(1, int(building.DISPLAY_W * camera.zoom))
    h = max(1, int(building.DISPLAY_H * camera.zoom))
    scaled = get_scaled(surf, w, h)
    sx, sy = camera.world_to_screen(building.x, building.y)
    surface.blit(scaled, (int(sx - w / 2), int(sy - h / 2)))
    if building.selected:
        pygame.draw.rect(surface, (255, 220, 0),
                         (int(sx - w / 2), int(sy - h / 2), w, h), 2)
    draw_health_bar(building, surface, camera, width=building.HEALTH_BAR_WIDTH)


# ---------------------------------------------------------------------------
# Blueprint renderer
# ---------------------------------------------------------------------------

def render_blueprint(blueprint, surface: pygame.Surface, camera) -> None:
    b     = blueprint._building
    ratio = blueprint.progress / b.max_hp

    surf   = _load_building_surf(b.sprite_key)
    w      = max(1, int(b.DISPLAY_W * camera.zoom))
    h      = max(1, int(b.DISPLAY_H * camera.zoom))
    scaled = get_scaled(surf, w, h).copy()
    scaled.set_alpha(int(60 + ratio * 180))
    sx, sy = camera.world_to_screen(b.x, b.y)
    surface.blit(scaled, (int(sx - w / 2), int(sy - h / 2)))

    bar_w = max(20, int(w * 0.6))
    bar_h = max(4, int(6 * camera.zoom))
    bx    = int(sx - bar_w / 2)
    by    = int(sy - h / 2 - bar_h - 4)
    pygame.draw.rect(surface, (40, 40, 40),    (bx, by, bar_w, bar_h))
    fill  = int(bar_w * ratio)
    if fill > 0:
        pygame.draw.rect(surface, (255, 200, 50), (bx, by, fill,  bar_h))
    pygame.draw.rect(surface, (0, 0, 0),       (bx, by, bar_w, bar_h), 1)


# ---------------------------------------------------------------------------
# Arrow renderer
# ---------------------------------------------------------------------------

_ARROW_DISPLAY_SIZE = 32  # render size in world px

_arrow_surfs: dict[str, pygame.Surface] = {}


def _load_arrow_surf(team: str) -> pygame.Surface:
    surf = _arrow_surfs.get(team)
    if surf is None:
        path = f"assets/Units/{team.capitalize()} Units/Archer/Arrow.png"
        surf = pygame.image.load(path).convert_alpha()
        _arrow_surfs[team] = surf
    return surf


def render_arrow(arrow, surface: pygame.Surface, camera) -> None:
    if not arrow.alive:
        return
    surf    = _load_arrow_surf(arrow.team)
    size    = max(1, int(_ARROW_DISPLAY_SIZE * camera.zoom))
    rotated = get_scaled_rotated(surf, size, arrow._angle)
    sx, sy  = camera.world_to_screen(arrow.x, arrow.y)
    rect    = rotated.get_rect(center=(int(sx), int(sy)))
    surface.blit(rotated, rect)


# ---------------------------------------------------------------------------
# Resource renderers
# ---------------------------------------------------------------------------

_gold_frames:  dict[str, list[pygame.Surface]] = {}   # sprite_key → frame list
_wood_frames:  dict[str, list[pygame.Surface]] = {}
_wood_stumps:  dict[str, pygame.Surface]       = {}
_sheep_frames: dict[str, list[pygame.Surface]] = {}   # anim name → frame list


def _load_sheet(path: str, frame_w: int) -> list[pygame.Surface]:
    sheet   = pygame.image.load(path).convert_alpha()
    frame_h = sheet.get_height()
    count   = sheet.get_width() // frame_w
    return [
        sheet.subsurface(pygame.Rect(i * frame_w, 0, frame_w, frame_h))
        for i in range(count)
    ]


def _get_gold_frames(sprite_key: str) -> list[pygame.Surface]:
    frames = _gold_frames.get(sprite_key)
    if frames is None:
        # sprite_key: "resource/gold/{n}"
        n      = sprite_key.split("/")[2]
        path   = f"assets/Terrain/Resources/Gold/Gold Stones/Gold Stone {n}_Highlight.png"
        frames = _load_sheet(path, 128)
        _gold_frames[sprite_key] = frames
    return frames


def _get_wood_frames(sprite_key: str) -> list[pygame.Surface]:
    frames = _wood_frames.get(sprite_key)
    if frames is None:
        n      = sprite_key.split("/")[2]
        frames = _load_sheet(f"assets/Terrain/Resources/Wood/Trees/Tree{n}.png", 192)
        _wood_frames[sprite_key] = frames
    return frames


def _get_wood_stump(sprite_key: str) -> pygame.Surface:
    stump = _wood_stumps.get(sprite_key)
    if stump is None:
        n     = sprite_key.split("/")[2]
        stump = pygame.image.load(
            f"assets/Terrain/Resources/Wood/Trees/Stump {n}.png"
        ).convert_alpha()
        _wood_stumps[sprite_key] = stump
    return stump


_SHEEP_PATHS = {
    "idle":      ("assets/Terrain/Resources/Meat/Sheep/Sheep_Idle.png",  128),
    "eat_grass": ("assets/Terrain/Resources/Meat/Sheep/Sheep_Grass.png", 128),
    "move":      ("assets/Terrain/Resources/Meat/Sheep/Sheep_Move.png",  128),
    "flee":      ("assets/Terrain/Resources/Meat/Sheep/Sheep_Move.png",  128),
}


def _get_sheep_frames(state: str) -> list[pygame.Surface]:
    frames = _sheep_frames.get(state)
    if frames is None:
        path, fw   = _SHEEP_PATHS[state]
        frames     = _load_sheet(path, fw)
        _sheep_frames[state] = frames
    return frames


def render_resource(node, surface: pygame.Surface, camera) -> None:
    from entities.resource import GoldNode, WoodNode, MeatNode
    if isinstance(node, GoldNode):
        _render_gold(node, surface, camera)
    elif isinstance(node, WoodNode):
        _render_wood(node, surface, camera)
    elif isinstance(node, MeatNode):
        _render_meat(node, surface, camera)


def _render_gold(node, surface: pygame.Surface, camera) -> None:
    if node.depleted:
        return
    frames = _get_gold_frames(node.sprite_key)
    frame  = frames[node._frame_idx % len(frames)]
    size   = max(1, int(node.DISPLAY_SIZE * camera.zoom))
    scaled = get_scaled(frame, size, size)
    sx, sy = camera.world_to_screen(node.x, node.y)
    surface.blit(scaled, (int(sx - size / 2), int(sy - size / 2)))


def _render_wood(node, surface: pygame.Surface, camera) -> None:
    sx, sy = camera.world_to_screen(node.x, node.y)
    size   = max(1, int(node.DISPLAY_SIZE * camera.zoom))
    if node.depleted:
        stump = _get_wood_stump(node.sprite_key)
        sw    = max(1, int(size * 192 / 256))
        scaled = get_scaled(stump, sw, size)
        surface.blit(scaled, (int(sx - sw / 2), int(sy - size / 2)))
        return
    frames = _get_wood_frames(node.sprite_key)
    frame  = frames[node._frame_idx % len(frames)]
    scaled = get_scaled(frame, size, size)
    surface.blit(scaled, (int(sx - size / 2), int(sy - size / 2)))


def _render_meat(node, surface: pygame.Surface, camera) -> None:
    if node.depleted:
        return
    frames = _get_sheep_frames(node._sheep_state)
    frame  = frames[node._frame_idx % len(frames)]
    size   = max(1, int(node.DISPLAY_SIZE * camera.zoom))
    scaled = get_scaled(frame, size, size, flip_x=not node._facing_right)
    sx, sy = camera.world_to_screen(node.x, node.y)
    surface.blit(scaled, (int(sx - size / 2), int(sy - size / 2)))


# ---------------------------------------------------------------------------
# Pawn renderer
# ---------------------------------------------------------------------------

_PAWN_FILENAMES: dict[str, str] = {
    "idle":             "Pawn_Idle.png",
    "run":              "Pawn_Run.png",
    "run_axe":          "Pawn_Run Axe.png",
    "run_pickaxe":      "Pawn_Run Pickaxe.png",
    "run_knife":        "Pawn_Run Knife.png",
    "interact_axe":     "Pawn_Interact Axe.png",
    "interact_pickaxe": "Pawn_Interact Pickaxe.png",
    "interact_knife":   "Pawn_Interact Knife.png",
    "run_wood":         "Pawn_Run Wood.png",
    "run_gold":         "Pawn_Run Gold.png",
    "run_meat":         "Pawn_Run Meat.png",
    "run_hammer":       "Pawn_Run Hammer.png",
    "interact_hammer":  "Pawn_Interact Hammer.png",
}

# (team, anim_key) → frame list
_pawn_frames: dict[tuple[str, str], list[pygame.Surface]] = {}


def _get_pawn_frames(team: str, anim_key: str) -> list[pygame.Surface]:
    cache_key = (team, anim_key)
    frames = _pawn_frames.get(cache_key)
    if frames is None:
        filename = _PAWN_FILENAMES[anim_key]
        path     = f"assets/Units/{team.capitalize()} Units/Pawn/{filename}"
        frames   = _load_sheet(path, 192)
        _pawn_frames[cache_key] = frames
    return frames


def render_pawn(pawn, surface: pygame.Surface, camera) -> None:
    frames  = _get_pawn_frames(pawn.team, pawn._anim_key)
    frame   = frames[pawn._frame_idx % len(frames)]
    size    = max(1, int(pawn.DISPLAY_SIZE * camera.zoom))
    flip_x  = not pawn._facing_right
    scaled  = get_scaled(frame, size, size, flip_x=flip_x)
    sx, sy  = camera.world_to_screen(pawn.x, pawn.y)
    surface.blit(scaled, (int(sx - size / 2), int(sy - size / 2)))
    if pawn.selected:
        r = max(2, int(pawn.SELECT_RADIUS * camera.zoom))
        pygame.draw.circle(surface, (255, 220, 0), (int(sx), int(sy)), r, 2)
    draw_health_bar(pawn, surface, camera)
    if pawn._task == "to_depot" and pawn._carried > 0:
        font  = get_font(max(12, int(16 * camera.zoom)))
        label = font.render(str(int(pawn._carried)), True, (255, 255, 180))
        surface.blit(label, (int(sx), int(sy - size / 2 - 14 * camera.zoom)))


# ---------------------------------------------------------------------------
# Archer renderer
# ---------------------------------------------------------------------------

_ARCHER_FILENAMES: dict[str, str] = {
    "idle":   "Archer_Idle.png",
    "run":    "Archer_Run.png",
    "attack": "Archer_Shoot.png",
}

_archer_frames: dict[tuple[str, str], list[pygame.Surface]] = {}


def _get_archer_frames(team: str, anim_key: str) -> list[pygame.Surface]:
    key    = (team, anim_key)
    frames = _archer_frames.get(key)
    if frames is None:
        path   = f"assets/Units/{team.capitalize()} Units/Archer/{_ARCHER_FILENAMES[anim_key]}"
        frames = _load_sheet(path, 192)
        _archer_frames[key] = frames
    return frames


def render_archer(archer, surface: pygame.Surface, camera) -> None:
    frames = _get_archer_frames(archer.team, archer._anim_key)
    frame  = frames[archer._frame_idx % len(frames)]
    size   = max(1, int(archer.DISPLAY_SIZE * camera.zoom))
    scaled = get_scaled(frame, size, size, flip_x=not archer._facing_right)
    sx, sy = camera.world_to_screen(archer.x, archer.y)
    surface.blit(scaled, (int(sx - size / 2), int(sy - size / 2)))
    if archer.selected:
        r = max(2, int(archer.SELECT_RADIUS * camera.zoom))
        pygame.draw.circle(surface, (255, 220, 0), (int(sx), int(sy)), r, 2)
    draw_health_bar(archer, surface, camera)


# ---------------------------------------------------------------------------
# Lancer renderer
# ---------------------------------------------------------------------------

_LANCER_DIRS = ("Right", "UpRight", "Up", "Down", "DownRight")

# (team, anim, dir_key) → frame list  (dir_key="" for idle/run)
_lancer_frames: dict[tuple, list[pygame.Surface]] = {}


def _get_lancer_frames(team: str, anim: str, dir_key: str = "") -> list[pygame.Surface]:
    key    = (team, anim, dir_key)
    frames = _lancer_frames.get(key)
    if frames is None:
        folder = f"assets/Units/{team.capitalize()} Units/Lancer"
        if anim == "attack":
            path = f"{folder}/Lancer_{dir_key}_Attack.png"
        elif anim == "defence":
            path = f"{folder}/Lancer_{dir_key}_Defence.png"
        elif anim == "run":
            path = f"{folder}/Lancer_Run.png"
        else:
            path = f"{folder}/Lancer_Idle.png"
        frames = _load_sheet(path, 320)
        _lancer_frames[key] = frames
    return frames


def render_lancer(lancer, surface: pygame.Surface, camera) -> None:
    state = lancer._state
    idx   = lancer._frame_idx

    if state == "attack":
        frames = _get_lancer_frames(lancer.team, "attack", lancer._dir_key)
        flip_x = lancer._flip_dir
    elif state == "defence":
        frames = _get_lancer_frames(lancer.team, "defence", lancer._def_dir_key)
        flip_x = lancer._def_flip
    elif state == "run":
        frames = _get_lancer_frames(lancer.team, "run")
        flip_x = not lancer._facing_right
    else:
        frames = _get_lancer_frames(lancer.team, "idle")
        flip_x = not lancer._facing_right

    frame  = frames[idx % len(frames)]
    size   = max(1, int(lancer.DISPLAY_SIZE * camera.zoom))
    scaled = get_scaled(frame, size, size, flip_x=flip_x)
    sx, sy = camera.world_to_screen(lancer.x, lancer.y)
    surface.blit(scaled, (int(sx - size / 2), int(sy - size / 2)))
    if lancer.selected:
        r = max(2, int(lancer.SELECT_RADIUS * camera.zoom))
        pygame.draw.circle(surface, (255, 220, 0), (int(sx), int(sy)), r, 2)
    draw_health_bar(lancer, surface, camera)


# ---------------------------------------------------------------------------
# Warrior renderer
# ---------------------------------------------------------------------------

_WARRIOR_FILENAMES: dict[str, str] = {
    "idle":    "Warrior_Idle.png",
    "run":     "Warrior_Run.png",
    "attack1": "Warrior_Attack1.png",
    "attack2": "Warrior_Attack2.png",
    "guard":   "Warrior_Guard.png",
}

_warrior_frames: dict[tuple[str, str], list[pygame.Surface]] = {}


def _get_warrior_frames(team: str, anim_key: str) -> list[pygame.Surface]:
    key    = (team, anim_key)
    frames = _warrior_frames.get(key)
    if frames is None:
        path   = f"assets/Units/{team.capitalize()} Units/Warrior/{_WARRIOR_FILENAMES[anim_key]}"
        frames = _load_sheet(path, 192)
        _warrior_frames[key] = frames
    return frames


def render_warrior(warrior, surface: pygame.Surface, camera) -> None:
    frames = _get_warrior_frames(warrior.team, warrior._anim_key)
    frame  = frames[warrior._frame_idx % len(frames)]
    size   = max(1, int(warrior.DISPLAY_SIZE * camera.zoom))
    scaled = get_scaled(frame, size, size, flip_x=not warrior._facing_right)
    sx, sy = camera.world_to_screen(warrior.x, warrior.y)
    surface.blit(scaled, (int(sx - size / 2), int(sy - size / 2)))
    if warrior.selected:
        r = max(2, int(warrior.SELECT_RADIUS * camera.zoom))
        pygame.draw.circle(surface, (255, 220, 0), (int(sx), int(sy)), r, 2)
    draw_health_bar(warrior, surface, camera)
