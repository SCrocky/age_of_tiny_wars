"""
Asset loader — reads images directly from the Tiny Swords zip bundle.

The zip path is resolved from, in order:
  1. ASSETS_ZIP environment variable
  2. 'Tiny Swords (Free Pack).zip' next to the game files

All callers pass the same 'assets/...' path they always did.
"""
from __future__ import annotations
import io
import os
import zipfile
import pygame

_ZIP_ROOT     = "Tiny Swords (Free Pack)/"
_ZIP_FILENAME = "downloaded_assets/Tiny Swords (Free Pack).zip"

_zf:    zipfile.ZipFile | None = None
_ready: bool = False


def _init() -> None:
    global _zf, _ready
    if _ready:
        return
    _ready = True

    path = os.environ.get("ASSETS_ZIP") or _ZIP_FILENAME
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"\n\nAsset pack not found at '{path}'.\n"
            "Download 'Tiny Swords (Free Pack).zip' from:\n"
            "  https://pixelfrog-assets.itch.io/tiny-swords\n"
            f"and place it in '{os.path.dirname(os.path.abspath(path))}'.\n"
        )
    _zf = zipfile.ZipFile(path, "r")


def _to_zip_path(game_path: str) -> str:
    return f"{_ZIP_ROOT}{game_path.removeprefix('assets/')}"


def load_image(path: str) -> pygame.Surface:
    _init()
    data = _zf.read(_to_zip_path(path))
    return pygame.image.load(io.BytesIO(data), os.path.basename(path))
