import json
import os
import random
import sys
from datetime import datetime

import pygame

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_DIR, "map_editor"))
import create_map as _cm
import populate_map as _pm

from game import Game

SCREEN_WIDTH = 1600
SCREEN_HEIGHT = 900
FPS = 60


def _generate_scene() -> str:
    """Generate a fresh map+scene, return path to the scene JSON."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem  = os.path.join(_DIR, "map_editor", "maps", f"map_{stamp}")

    seed = random.randrange(2 ** 32)
    rng  = random.Random(seed)

    grid              = _cm.make_grid()
    zones             = _cm.assign_zones(rng)
    resources, spawns = _cm.place_resources(rng, zones, grid)
    map_data         = _cm.build_output(grid, zones, resources, spawns, seed)
    buildings, units = _pm.populate(map_data)
    scene            = _pm.build_scene(map_data, buildings, units, stem)

    scene_path = stem + "_scene.json"
    with open(scene_path, "w") as f:
        json.dump(scene, f, separators=(",", ":"))

    print(f"Generated map: {scene_path}")
    return scene_path


def main():
    scene_path = _generate_scene()

    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.FULLSCREEN)
    pygame.display.set_caption("Age of Wars")
    clock = pygame.time.Clock()

    game = Game(screen, scene_path=scene_path)

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            game.handle_event(event)

        game.update(dt)
        game.render()
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
