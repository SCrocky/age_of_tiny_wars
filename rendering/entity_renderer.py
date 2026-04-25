from __future__ import annotations
import pygame
from pygame._sdl2.video import Renderer
from texture_cache import get_texture, make_texture, get_font, get_circle_tex
from entities.pawn import Task as PawnTask
import assets

# ---------------------------------------------------------------------------
# Surface caches — keyed by sprite_key string.
# Surfaces are loaded on first use; no Pygame state needed at import time.
# ---------------------------------------------------------------------------

_building_surfs: dict[str, pygame.Surface] = {}

_BUILDING_FILENAMES: dict[str, str] = {
    "archery":  "Archery.png",
    "barracks": "Barracks.png",
    "castle":   "Castle.png",
    "house1":   "House1.png",
    "house2":   "House2.png",
    "house3":   "House3.png",
    "tower":    "Tower.png",
}


def _load_building_surf(sprite_key: str) -> pygame.Surface:
    surf = _building_surfs.get(sprite_key)
    if surf is None:
        _, btype, team = sprite_key.split("/")
        filename = _BUILDING_FILENAMES[btype]
        path = f"assets/Buildings/{team.capitalize()} Buildings/{filename}"
        surf = assets.load_image(path)
        _building_surfs[sprite_key] = surf
    return surf


# ---------------------------------------------------------------------------
# Shared drawing helpers
# ---------------------------------------------------------------------------

def draw_selection_circle(renderer: Renderer, cx: int, cy: int, r: int) -> None:
    d = r * 2
    get_circle_tex().draw(dstrect=(cx - r, cy - r, d, d))


def draw_health_bar(
    entity,
    renderer: Renderer,
    camera,
    width: int = 40,
    force: bool = False,
) -> None:
    if not force and not entity.selected and entity.hp == entity.max_hp:
        return

    sx, sy = camera.world_to_screen(entity.x, entity.y)
    bar_w = int(width * camera.zoom)
    bar_h = max(3, int(4 * camera.zoom))
    bx = int(sx - bar_w / 2)
    by = int(sy - int(36 * camera.zoom))

    renderer.draw_blend_mode = pygame.BLENDMODE_NONE
    renderer.draw_color = (80, 0, 0, 255)
    renderer.fill_rect(pygame.Rect(bx, by, bar_w, bar_h))
    fill = int(bar_w * entity.hp / entity.max_hp)
    if fill > 0:
        renderer.draw_color = (0, 200, 60, 255)
        renderer.fill_rect(pygame.Rect(bx, by, fill, bar_h))
    renderer.draw_color = (0, 0, 0, 255)
    renderer.draw_rect(pygame.Rect(bx, by, bar_w, bar_h))


# ---------------------------------------------------------------------------
# Building renderer
# ---------------------------------------------------------------------------

def render_building(building, renderer: Renderer, camera) -> None:
    if not building.alive:
        return
    surf = _load_building_surf(building.sprite_key)
    w = max(1, int(building.DISPLAY_W * camera.zoom))
    h = max(1, int(building.DISPLAY_H * camera.zoom))
    sx, sy = camera.world_to_screen(building.x, building.y)
    get_texture(surf).draw(dstrect=(int(sx - w / 2), int(sy - h / 2), w, h))
    if building.selected:
        renderer.draw_blend_mode = pygame.BLENDMODE_NONE
        renderer.draw_color = (255, 220, 0, 255)
        renderer.draw_rect(pygame.Rect(int(sx - w / 2), int(sy - h / 2), w, h))
    draw_health_bar(building, renderer, camera, width=building.HEALTH_BAR_WIDTH)

    if getattr(building, "garrisoned", False):
        _render_garrisoned_archer(building, renderer, camera)


def _render_garrisoned_archer(tower, renderer: Renderer, camera) -> None:
    frames = _get_archer_frames(tower.team, tower.garrisoned_anim_key)
    frame  = frames[tower.garrisoned_frame_idx % len(frames)]
    size   = max(1, int(96 * camera.zoom))
    sx, sy = camera.world_to_screen(tower.x, tower.y)
    # Position the archer near the top of the tower sprite
    sy    -= int(tower.DISPLAY_H * camera.zoom * 0.20)
    get_texture(frame).draw(
        dstrect=(int(sx - size / 2), int(sy - size / 2), size, size),
        flip_x=not tower.garrisoned_facing_right,
    )


# ---------------------------------------------------------------------------
# Blueprint renderer
# ---------------------------------------------------------------------------

def render_blueprint(blueprint, renderer: Renderer, camera) -> None:
    b     = blueprint._building
    ratio = blueprint.progress / b.max_hp

    surf = _load_building_surf(b.sprite_key)
    w    = max(1, int(b.DISPLAY_W * camera.zoom))
    h    = max(1, int(b.DISPLAY_H * camera.zoom))
    tex  = get_texture(surf)
    tex.alpha = int(60 + ratio * 180)
    sx, sy = camera.world_to_screen(b.x, b.y)
    tex.draw(dstrect=(int(sx - w / 2), int(sy - h / 2), w, h))
    tex.alpha = 255

    bar_w = max(20, int(w * 0.6))
    bar_h = max(4, int(6 * camera.zoom))
    bx    = int(sx - bar_w / 2)
    by    = int(sy - h / 2 - bar_h - 4)
    renderer.draw_blend_mode = pygame.BLENDMODE_NONE
    renderer.draw_color = (40, 40, 40, 255)
    renderer.fill_rect(pygame.Rect(bx, by, bar_w, bar_h))
    fill = int(bar_w * ratio)
    if fill > 0:
        renderer.draw_color = (255, 200, 50, 255)
        renderer.fill_rect(pygame.Rect(bx, by, fill, bar_h))
    renderer.draw_color = (0, 0, 0, 255)
    renderer.draw_rect(pygame.Rect(bx, by, bar_w, bar_h))


# ---------------------------------------------------------------------------
# Arrow renderer
# ---------------------------------------------------------------------------

_ARROW_DISPLAY_SIZE = 32

_arrow_surfs: dict[str, pygame.Surface] = {}


def _load_arrow_surf(team: str) -> pygame.Surface:
    surf = _arrow_surfs.get(team)
    if surf is None:
        path = f"assets/Units/{team.capitalize()} Units/Archer/Arrow.png"
        surf = assets.load_image(path)
        _arrow_surfs[team] = surf
    return surf


def render_arrow(arrow, renderer: Renderer, camera) -> None:
    if not arrow.alive:
        return
    size   = max(1, int(_ARROW_DISPLAY_SIZE * camera.zoom))
    sx, sy = camera.world_to_screen(arrow.x, arrow.y)
    # pygame.transform.rotate is CCW; SDL2 Texture.draw(angle) is CW — negate.
    get_texture(_load_arrow_surf(arrow.team)).draw(
        dstrect=(int(sx - size / 2), int(sy - size / 2), size, size),
        angle=-arrow._angle,
    )


# ---------------------------------------------------------------------------
# Resource renderers
# ---------------------------------------------------------------------------

_gold_frames:  dict[str, list[pygame.Surface]] = {}
_wood_frames:  dict[str, list[pygame.Surface]] = {}
_wood_stumps:  dict[str, pygame.Surface]       = {}
_sheep_frames: dict[str, list[pygame.Surface]] = {}


def _load_sheet(path: str, frame_w: int) -> list[pygame.Surface]:
    sheet   = assets.load_image(path)
    frame_h = sheet.get_height()
    count   = sheet.get_width() // frame_w
    return [
        sheet.subsurface(pygame.Rect(i * frame_w, 0, frame_w, frame_h))
        for i in range(count)
    ]


def _get_gold_frames(sprite_key: str) -> list[pygame.Surface]:
    frames = _gold_frames.get(sprite_key)
    if frames is None:
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
        stump = assets.load_image(
            f"assets/Terrain/Resources/Wood/Trees/Stump {n}.png"
        )
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


def render_resource(node, renderer: Renderer, camera) -> None:
    res_type = getattr(node, "resource_type", None)
    if res_type is None:
        from entities.resource import GoldNode, WoodNode, MeatNode
        if isinstance(node, GoldNode):   res_type = "gold"
        elif isinstance(node, WoodNode): res_type = "wood"
        elif isinstance(node, MeatNode): res_type = "meat"

    if res_type == "gold":   _render_gold(node, renderer, camera)
    elif res_type == "wood": _render_wood(node, renderer, camera)
    elif res_type == "meat": _render_meat(node, renderer, camera)


def _render_gold(node, renderer: Renderer, camera) -> None:
    if node.depleted:
        return
    frames = _get_gold_frames(node.sprite_key)
    frame  = frames[node._frame_idx % len(frames)]
    size   = max(1, int(node.DISPLAY_SIZE * camera.zoom))
    sx, sy = camera.world_to_screen(node.x, node.y)
    get_texture(frame).draw(dstrect=(int(sx - size / 2), int(sy - size / 2), size, size))


def _render_wood(node, renderer: Renderer, camera) -> None:
    sx, sy = camera.world_to_screen(node.x, node.y)
    size   = max(1, int(node.DISPLAY_SIZE * camera.zoom))
    if node.depleted:
        stump = _get_wood_stump(node.sprite_key)
        sw    = max(1, int(size * 192 / 256))
        get_texture(stump).draw(dstrect=(int(sx - sw / 2), int(sy - size / 2), sw, size))
        return
    frames = _get_wood_frames(node.sprite_key)
    frame  = frames[node._frame_idx % len(frames)]
    get_texture(frame).draw(dstrect=(int(sx - size / 2), int(sy - size / 2), size, size))


def _render_meat(node, renderer: Renderer, camera) -> None:
    if node.depleted:
        return
    frames = _get_sheep_frames(node._sheep_state)
    frame  = frames[node._frame_idx % len(frames)]
    size   = max(1, int(node.DISPLAY_SIZE * camera.zoom))
    sx, sy = camera.world_to_screen(node.x, node.y)
    get_texture(frame).draw(
        dstrect=(int(sx - size / 2), int(sy - size / 2), size, size),
        flip_x=not node._facing_right,
    )


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


def render_pawn(pawn, renderer: Renderer, camera) -> None:
    frames = _get_pawn_frames(pawn.team, pawn._anim_key)
    frame  = frames[pawn._frame_idx % len(frames)]
    size   = max(1, int(pawn.DISPLAY_SIZE * camera.zoom))
    sx, sy = camera.world_to_screen(pawn.x, pawn.y)
    get_texture(frame).draw(
        dstrect=(int(sx - size / 2), int(sy - size / 2), size, size),
        flip_x=not pawn._facing_right,
    )
    if pawn.selected:
        r = max(2, int(pawn.SELECT_RADIUS * camera.zoom))
        draw_selection_circle(renderer, int(sx), int(sy), r)
    draw_health_bar(pawn, renderer, camera)
    task_val = pawn._task.value if isinstance(pawn._task, PawnTask) else pawn._task
    if task_val == "to_depot" and pawn._carried > 0:
        font     = get_font(max(12, int(16 * camera.zoom)))
        lbl_surf = font.render(str(int(pawn._carried)), True, (255, 255, 180))
        lbl_tex  = make_texture(lbl_surf)
        lw, lh   = lbl_surf.get_size()
        lbl_tex.draw(dstrect=(int(sx), int(sy - size / 2 - 14 * camera.zoom), lw, lh))


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


def render_archer(archer, renderer: Renderer, camera) -> None:
    frames = _get_archer_frames(archer.team, archer._anim_key)
    frame  = frames[archer._frame_idx % len(frames)]
    size   = max(1, int(archer.DISPLAY_SIZE * camera.zoom))
    sx, sy = camera.world_to_screen(archer.x, archer.y)
    get_texture(frame).draw(
        dstrect=(int(sx - size / 2), int(sy - size / 2), size, size),
        flip_x=not archer._facing_right,
    )
    if archer.selected:
        r = max(2, int(archer.SELECT_RADIUS * camera.zoom))
        draw_selection_circle(renderer, int(sx), int(sy), r)
    draw_health_bar(archer, renderer, camera)


# ---------------------------------------------------------------------------
# Lancer renderer
# ---------------------------------------------------------------------------

_LANCER_DIRS = ("Right", "UpRight", "Up", "Down", "DownRight")

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


def render_lancer(lancer, renderer: Renderer, camera) -> None:
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
    sx, sy = camera.world_to_screen(lancer.x, lancer.y)
    get_texture(frame).draw(
        dstrect=(int(sx - size / 2), int(sy - size / 2), size, size),
        flip_x=flip_x,
    )
    if lancer.selected:
        r = max(2, int(lancer.SELECT_RADIUS * camera.zoom))
        draw_selection_circle(renderer, int(sx), int(sy), r)
    draw_health_bar(lancer, renderer, camera)


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


def render_warrior(warrior, renderer: Renderer, camera) -> None:
    frames = _get_warrior_frames(warrior.team, warrior._anim_key)
    frame  = frames[warrior._frame_idx % len(frames)]
    size   = max(1, int(warrior.DISPLAY_SIZE * camera.zoom))
    sx, sy = camera.world_to_screen(warrior.x, warrior.y)
    get_texture(frame).draw(
        dstrect=(int(sx - size / 2), int(sy - size / 2), size, size),
        flip_x=not warrior._facing_right,
    )
    if warrior.selected:
        r = max(2, int(warrior.SELECT_RADIUS * camera.zoom))
        draw_selection_circle(renderer, int(sx), int(sy), r)
    draw_health_bar(warrior, renderer, camera)
