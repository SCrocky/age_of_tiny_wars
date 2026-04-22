# Age of Wars

A free, open-source medieval RTS built with Python and Pygame. Gather resources, raise an army, and crush your enemies — alone or with a friend over LAN.

No installs beyond Python. No accounts. No monetisation. Ever.

---

## Play

```bash
pip install -r requirements.txt

# Single-player
python main.py

# Multiplayer — host
python server_main.py

# Multiplayer — join
python client_main.py
```

---

## How it works

Collect **gold**, **wood**, and **meat** to build up your base and train troops. Your **Castle** is both your stronghold and spawn point — lose it and it's over.

| Building | Purpose |
|---|---|
| Castle | Base, spawns Pawns |
| House | Raises population cap, acts as a resource depot |
| Archery | Trains Archers |
| Barracks | Trains Warriors and Lancers |

| Unit | Role |
|---|---|
| Pawn | Gathers resources, constructs buildings |
| Archer | Ranged — picks off enemies from a distance |
| Warrior | Heavy melee — blocks the first hit every swing |
| Lancer | Fast melee — 8-directional attacks |

---

## Controls

| Input | Action |
|---|---|
| Left-click | Select unit / building |
| Click + drag | Box-select multiple units |
| Shift + click | Add to selection |
| Right-click unit / building | Attack |
| Right-click resource | Gather (Pawns) |
| Right-click ground | Move |
| Arrow keys | Pan camera |
| Mouse wheel | Zoom |
| ESC | Cancel pending action |

---

## Contributing

This game is a gift to the community — and a work in progress. If you want to help shape it, you're very welcome.

Good places to start:

- **New unit or building** — add a class under `entities/`, drop a sprite in `assets/`, register it in `game.py`
- **New map** — edit or extend `map_editor/` to generate different terrain layouts
- **Balance tweaks** — unit stats live at the top of each file in `entities/`
- **Bug reports** — open an issue, describe what happened and how to reproduce it
- **Art** — sprites are plain PNGs, 192×192 for units. Any style that fits the medieval theme is welcome

The codebase is intentionally kept readable. There's no build step and no framework magic — just Python files you can open and change.

---

## Credits

All in-game art is from the **[Tiny Swords (Free Pack)](https://pixelfrog-assets.itch.io/tiny-swords)** asset pack by **[Pixel Frog](https://pixelfrog-assets.itch.io/)**, released for free use. Thank you for making beautiful work freely available to the community.

---

## Contributors

A big thank you to everyone who has played, reported bugs, or sent a PR — you're what keeps this project alive.

Want to go deeper? Check out the [contributor guide](https://github.com/SCrocky/age_of_wars/blob/master/MORE_INFO.md) for architecture notes, coding conventions, and a roadmap of planned features.
