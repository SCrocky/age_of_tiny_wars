# Age of Wars

A medieval top-down 2D real-time strategy game built with Python and Pygame.
Supports up to 5 players in a free-for-all match — any mix of humans (over LAN)
and rule-based AI opponents.

---

## Getting Started

The game is split into a dedicated server and a thin rendering client. There is
no separate single-player binary — single-player is just one human seat plus AI
seats running on the same machine.

### Single Player (vs AI)

```bash
pip install -r requirements.txt
python server_main.py --players blue=human,black=ai
python client_main.py
```

### Multiplayer (LAN)

**On the host machine:**
```bash
python server_main.py --players blue=human,red=human,yellow=human
```

**On each client:**
```bash
python client_main.py --host <server-ip> --port 9876
```

Connection order maps to the team order in `--players`: the first client to
connect takes the first `human` seat, the second takes the second, and so on.
`ai` seats are filled automatically by an in-process bot. The match starts as
soon as every human seat is connected.

The server auto-generates a procedural map sized for the configured player
count, or you can pass `--scene path/to/scene.json` to use an existing map.

---

## Design

| Aspect | Decision |
|---|---|
| Perspective | Top-down 2D pixel art (chibi style) |
| Scope | 2–5 player FFA, full RTS economy + combat |
| Theme | Medieval |
| Factions | 5 team colors: blue, red, yellow, purple, black |
| Resources | Gold, Wood, Meat |
| Default match | `blue=human,black=human` (1v1 multiplayer) |

Players are interchangeable: every team has identical units, buildings, and
costs, distinguished only by sprite tint. Victory is last team standing — when
exactly one team still has a Castle, that team wins.

---

## Units

| Unit | Role |
|---|---|
| Pawn | Worker — gathers Gold, Wood, Meat; constructs buildings |
| Archer | Ranged attacker; fires homing Arrow projectiles |
| Lancer | Fast melee attacker with 8-directional attacks |
| Warrior | Melee tank with a guard mechanic that blocks the first hit per swing |
| Monk | Support — automatically heals nearby allied units |

---

## Buildings

| Building | Purpose |
|---|---|
| Castle | Main base; spawns Pawns, resource depot, +10 pop cap, lose this and you're out |
| House | Resource depot, +5 pop cap, three visual variants |
| Archery | Trains Archers |
| Barracks | Trains Lancers and Warriors |
| Monastery | Trains Monks |
| Tower | Defensive structure; garrison an Archer for extended range and damage |

**Construction**: Select a Pawn, choose a building from the HUD, then
right-click to place a blueprint. Multiple Pawns can contribute simultaneously;
the building activates when the blueprint reaches full health.

**Garrisoning**: Right-click a friendly Tower with an Archer selected to send
the Archer inside. While garrisoned, the Archer's range, fire rate, and arrow
damage are roughly doubled. Releasing puts the Archer back at the tower's foot.

---

## Resources

| Resource | Source | Pawn tool |
|---|---|---|
| Gold | Gold stone nodes (multiple size variants) | Pickaxe |
| Wood | Trees (→ Stump when depleted) | Axe |
| Meat | Sheep (autonomous wander/flee AI) | Knife |

---

## Controls

| Input | Action |
|---|---|
| Left-click | Select unit / building |
| Shift + left-click | Toggle selection |
| Left-click drag | Box-select multiple units |
| Right-click (empty) | Move selected units |
| Right-click (enemy) | Attack |
| Right-click (resource) | Gather (Pawns only) |
| Right-click (own Tower with Archer selected) | Garrison the Archer |
| Right-click (own Blueprint with Pawn selected) | Assign Pawn to construction |
| Arrow keys / edge scroll | Pan camera |
| Mouse wheel | Zoom (anchored on cursor) |
| H | Centre camera on your Castle |
| ESC | Cancel pending build / quit |
| HUD buttons | Train units / construct buildings |
| F3 | Toggle debug overlay (RTT) |
| D | Toggle entity debug overlay |

---

## Core Systems

**Game loop**
- 60 Hz authoritative tick on the server; 10 Hz snapshot broadcast to clients;
  60 Hz interpolated render on each client.

**Map & camera**
- Tile-based grid with GRASS and WATER terrain types and per-tile walkability.
- Camera supports keyboard pan, edge scrolling, and mouse-wheel zoom.
- `MapRenderer` keeps a tile texture cache so only visible tiles are drawn.

**Entities**
- `Entity` → `Unit` → `CombatUnit` (Archer/Lancer/Warrior) / `Monk` / `Pawn`
- `Entity` → `Building` (Castle/House/Archery/Barracks/Monastery/Tower)
- `Entity` → `Resource` (GoldNode/WoodNode/MeatNode) and `Blueprint` and
  `Arrow` (projectile)
- Sprite surfaces are loaded directly from the Tiny Swords zip via `assets.py`
  and cached as SDL textures by `texture_cache.py`.

**Pathfinding**
- A* on the 8-directional tile grid with an octile heuristic.
- Diagonal movement through blocked corners is prevented.
- Units re-path periodically while chasing a moving target.
- Soft-repulsion separation keeps units from stacking on top of each other.

**Selection & commands**
- Click to select; drag to box-select; Shift toggles selection.
- Right-click dispatch: Garrison / Attack / Gather / Build / Move based on
  what the cursor is over.
- Group movement fans units out in concentric rings around the destination.

**Economy**
- Per-team Gold / Wood / Meat counters; everyone starts with 60 of each.
- Population cap is the sum of `pop_bonus` over each team's living Castles
  (+10) and Houses (+5).
- Pawns cycle through gather → carry → deposit; any living Castle or House
  acts as a depot.

**Combat**
- Archer: fires a homing Arrow projectile.
- Lancer: 8-directional attack and defence animations.
- Warrior: alternates two attack animations; guard mechanic blocks the first
  hit within each attack cooldown.
- Monk: pure support — auto-heals the nearest wounded ally within range.
- Tower: when an Archer is garrisoned, the tower fires arrows with extended
  range, ~2× damage, and a faster cooldown.

**Production**
- Buildings spawn units instantly when their team can afford the cost.
- Trained units appear at a random angle within a short radius of the
  building.

**Blueprints**
- Blueprints render with increasing opacity as construction progresses.
- Multiple Pawns can contribute simultaneously; the building activates when
  the blueprint reaches full health.

**Fog of war**
- Per-team visibility computed from each unit/building's vision radius.
- Buildings and resources are remembered (explored) once seen; units only
  show inside the current visible area.

---

## Match Setup

`server_main.py` takes a single `--players` flag describing every seat. Each
token is `team=role`:

- `team`: one of `blue`, `red`, `yellow`, `purple`, `black` — must be unique
- `role`: `human` or `ai`
- 2–5 seats are supported

Examples:

```bash
# 1 human vs 3 AI
python server_main.py --players blue=human,red=ai,yellow=ai,purple=ai

# Five-way FFA (all humans)
python server_main.py --players blue=human,red=human,yellow=human,purple=human,black=human

# All-AI match for spectating
python server_main.py --players blue=ai,red=ai,yellow=ai,purple=ai,black=ai
```

Default with no flag is `blue=human,black=human` (multiplayer 1v1).

---

## Multiplayer Architecture

```
server_main.py                       client_main.py (×N humans)
└─ GameServer                        └─ ClientGame
     ├─ game.py (auth sim)                ├─ camera.py (local pan/zoom)
     │    └─ systems/pathfinding.py       ├─ rendering/hud_renderer.py
     ├─ asyncio TCP :9876                 ├─ rendering/map_renderer.py
     │    └─ msgpack snapshots            ├─ rendering/entity_renderer.py
     └─ AIPlayer per ai seat              ├─ rendering/minimap.py
          └─ ai/bot.py                    ├─ systems/fog.py
                                          └─ network/client.py
```

- **Authoritative server**: Runs the full simulation headlessly. No client
  ever advances state — all command results are observed via snapshots.
- **Wire protocol**: TCP with 4-byte big-endian length-prefix framing;
  msgpack payloads in both directions.
- **Snapshots**: Full game state broadcast at 10 Hz; clients interpolate
  positions between consecutive snapshots at 60 Hz for smooth motion.
- **Commands**: Clients send `CMD_MOVE`, `CMD_ATTACK`, `CMD_GATHER`,
  `CMD_SPAWN`, `CMD_BUILD`, `CMD_ASSIGN_BUILD`, `CMD_GARRISON`, `CMD_RELEASE`,
  `CMD_DEV_SPAWN`. The server queues them and applies on the next tick.
- **AI players**: Each `ai` seat is wired in-process via `AIPlayer`, which
  fakes a TCP `(reader, writer, team)` triple. AI logic lives in `ai/bot.py`
  and consumes the same `GAME_STATE` snapshots as humans.
- **Victory**: `_check_victory` returns the surviving team when exactly one
  team still has a living Castle. Game loop broadcasts `GAME_OVER` and exits.
- **Disconnect / forfeit**: When a client drops, the server pauses for up to
  30 seconds to allow reconnection. After the timeout, the team's Castles are
  destroyed; with 2 teams the survivor wins, with N>2 the remaining teams
  keep playing until one is left.

---

## Procedural Map Generation

`map_editor/create_map.py` generates maps using a Wave Function Collapse zone
algorithm:

1. Splits the interior into a 10×6 zone grid.
2. Spawn cells are picked from a fixed table indexed by player count
   (`_SPAWN_LAYOUTS`): opposite corners for N=2, a triangle for N=3, four
   corners for N=4, four corners + centre for N=5.
3. Adjacency rules bias resource-rich zones near spawns and prevent same-type
   blobs from forming.
4. Resources are placed in clumps — wood as line-arranged forest clusters,
   gold and meat scattered.
5. Outputs a JSON map file and a PNG preview.

`map_editor/populate_map.py` adds starting buildings and Pawns to a generated
map (one Castle and three Pawns per spawn) and produces the scene JSON that
the server loads.

Both scripts accept `--teams` to pick which colors get spawn points:

```bash
python map_editor/create_map.py --teams red,yellow,purple
```

---

## File Structure

```
age_of_tiny_wars/
├── server_main.py        # Server entry: --players parsing, scene gen, AI wiring
├── client_main.py        # Client entry: window/network thread, ClientGame loop
├── game.py               # Authoritative simulation: entities, update, economy
├── client_game.py        # Client-side rendering state — no simulation logic
├── map.py                # Tile map, terrain, walkability
├── camera.py             # Viewport pan/zoom, world↔screen coordinate conversion
├── assets.py             # Loads images directly from the Tiny Swords zip
├── texture_cache.py      # Surface → SDL2 texture cache
│
├── ai/
│   └── bot.py            # Rule-based AI: gather, train, build, attack
│
├── entities/
│   ├── teams.py          # The 5 team colors and avatar/banner mappings
│   ├── entity.py         # Base class: position, HP, team
│   ├── unit.py           # Base mover: pathfinding, animation
│   ├── combat_unit.py    # Shared combat behaviour (Archer/Lancer/Warrior)
│   ├── pawn.py           # Worker: gather → carry → deposit, build
│   ├── archer.py         # Ranged: fires Arrow projectiles
│   ├── lancer.py         # Melee: 8-directional attack/defence
│   ├── warrior.py        # Tank: guard mechanic, two-swing animation
│   ├── monk.py           # Support: auto-heals nearby allies
│   ├── building.py       # Castle, House, Archery, Barracks, Monastery, Tower
│   ├── resource.py       # GoldNode, WoodNode, MeatNode (sheep AI)
│   ├── projectile.py     # Arrow: homing, snap-to-hit
│   └── blueprint.py      # Building under construction
│
├── network/
│   ├── headless.py       # SDL dummy driver init for server-side pygame
│   ├── lobby.py          # Waits for human clients, assigns teams, fires GAME_START
│   ├── server.py         # GameServer: simulation + snapshot broadcast
│   ├── client.py         # Async TCP client with reconnect support
│   ├── ai_player.py      # AI seat: in-memory reader/writer wrapping a BotAI
│   ├── serialization.py  # msgpack encode/decode for snapshots and commands
│   └── render_proxy.py   # EntityProxy duck-typed wrappers for client rendering
│
├── rendering/
│   ├── map_renderer.py   # Tile rendering + per-team fog overlay
│   ├── entity_renderer.py# Building/unit/resource sprite drawing
│   ├── hud_renderer.py   # Resource bar, selection panel, build/train buttons
│   └── minimap.py        # Compact map overview with click-to-pan
│
├── systems/
│   ├── pathfinding.py    # A* with octile heuristic, corner-cut prevention
│   └── fog.py            # Per-team visible/explored tile masks
│
├── map_editor/
│   ├── create_map.py     # Procedural WFC map generator → JSON + PNG
│   ├── populate_map.py   # Adds starting buildings/units to a map
│   └── maps/             # Generated map files
│
├── downloaded_assets/
│   └── Tiny Swords (Free Pack).zip   # Asset pack, read directly (not extracted)
│
└── screenshots/          # Reference images for development
```

---

## Asset Structure

All sprites are loaded directly from `downloaded_assets/Tiny Swords (Free Pack).zip`
via `assets.py`. The expected layout inside the zip:

```
assets/
├── Buildings/
│   ├── Blue Buildings/      # Castle, Archery, Barracks, House1-3, Monastery, Tower
│   ├── Red Buildings/
│   ├── Yellow Buildings/
│   ├── Purple Buildings/
│   └── Black Buildings/
├── Units/
│   ├── <Color> Units/
│   │   ├── Archer/          # Idle, Run, Shoot
│   │   ├── Lancer/          # Idle, Run, Attack×8 dirs, Defence×8 dirs
│   │   ├── Warrior/         # Idle, Run, Attack1, Attack2
│   │   ├── Monk/            # Idle, Run, Heal
│   │   └── Pawn/            # Idle, Run + tool variants (Axe / Pickaxe / Knife / Hammer)
│   └── … one folder per team color
├── Terrain/
│   ├── Tileset/             # Tilemap color variants, water background, water foam
│   └── Resources/
│       ├── Gold/            # Gold stones (variants + highlights)
│       ├── Wood/            # Trees + stumps
│       └── Meat/            # Sheep idle/move/grass
└── UI_Elements/             # HUD avatars, banners, button frames
```

---

## Milestones

| # | Milestone | Status |
|---|---|---|
| 1 | Foundation: game loop, tile map, camera, sprites | ✅ Done |
| 2 | Units: animated units, A* pathfinding, click-to-move | ✅ Done |
| 3 | Combat: selection, attack commands, health bars, death | ✅ Done |
| 4 | Economy: Pawn gathering, resource counters, drop-off | ✅ Done |
| 5 | Buildings: place/train, blueprints, population cap | ✅ Done |
| 6 | Multiplayer: 2-player LAN PvP via authoritative server | ✅ Done |
| 7 | Fog of war: per-team visibility & exploration | ✅ Done |
| 8 | AI opponent: gather, train, build, attack | ✅ Done |
| 9 | Tower garrison + Monk support unit | ✅ Done |
| 10 | Multi-team support: 2–5 player FFA, any color mix | ✅ Done |
| 11 | Polish: sounds, music, victory cinematic | 🔲 Planned |
