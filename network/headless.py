import os


def init_headless():
    """Initialize pygame without a real display (for server use)."""
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    import pygame
    pygame.init()
    pygame.display.set_mode((1, 1))
