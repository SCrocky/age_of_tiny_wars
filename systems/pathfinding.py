import heapq
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, Future

# ---------------------------------------------------------------------------
# Async pool — workers run A* without holding the main-thread GIL
# ---------------------------------------------------------------------------

_pool: ProcessPoolExecutor | None = None
_mp_ctx = multiprocessing.get_context("spawn")


def _get_pool() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        workers = max(1, (os.cpu_count() or 2) - 1)
        _pool = ProcessPoolExecutor(max_workers=workers, mp_context=_mp_ctx)
    return _pool



# ---------------------------------------------------------------------------
# Standalone worker function (must be importable at module level for spawn)
# ---------------------------------------------------------------------------

def _astar_worker(
    cols: int,
    rows: int,
    tiles_flat: bytes,
    start: tuple,
    goal: tuple,
) -> list:
    """A* for worker processes — pure Python, no external dependencies."""

    def is_walkable(c: int, r: int) -> bool:
        if c < 0 or c >= cols or r < 0 or r >= rows:
            return False
        return tiles_flat[r * cols + c] == 0  # NavGrid: 0=walkable, 1=blocked

    if not is_walkable(*goal) or start == goal:
        return []

    CARDINAL = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    DIAGONAL  = [(1, 1), (1, -1), (-1, 1), (-1, -1)]

    def h(node):
        dx = abs(node[0] - goal[0])
        dy = abs(node[1] - goal[1])
        return max(dx, dy) + 0.414 * min(dx, dy)

    open_heap = [(h(start), start)]
    came_from: dict = {}
    g: dict = {start: 0.0}

    while open_heap:
        _, current = heapq.heappop(open_heap)

        if current == goal:
            path = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            path.reverse()
            return path

        for dc, dr in CARDINAL + DIAGONAL:
            nb = (current[0] + dc, current[1] + dr)
            if not is_walkable(*nb):
                continue
            step_cost = 1.0 if (dc == 0 or dr == 0) else 1.414
            if dc != 0 and dr != 0:
                if not is_walkable(current[0] + dc, current[1]) or \
                   not is_walkable(current[0], current[1] + dr):
                    continue
            tentative_g = g[current] + step_cost
            if tentative_g < g.get(nb, float("inf")):
                came_from[nb] = current
                g[nb] = tentative_g
                heapq.heappush(open_heap, (tentative_g + h(nb), nb))

    return []


def submit_astar(nav_grid, start: tuple, goal: tuple) -> Future:
    """Submit an A* request to the worker pool; returns a Future[list]."""
    return _get_pool().submit(
        _astar_worker,
        nav_grid.cols,
        nav_grid.rows,
        nav_grid.flat_bytes,
        start,
        goal,
    )


# ---------------------------------------------------------------------------
# Synchronous A* (used by Pawn and any callers needing an immediate result)
# ---------------------------------------------------------------------------

def astar(nav_grid, start: tuple[int, int], goal: tuple[int, int]) -> list[tuple[int, int]]:
    """
    A* on the nav grid (NavGrid or any object with is_walkable(col, row)).

    Parameters
    ----------
    nav_grid : NavGrid  — 16-px resolution grid; 0=walkable, 1=blocked
    start    : (col, row) in nav-grid coordinates
    goal     : (col, row) in nav-grid coordinates

    Returns
    -------
    List of (col, row) nav cells from *after* start up to and including goal.
    Empty list if no path exists.
    """
    if not nav_grid.is_walkable(*goal):
        return []
    if start == goal:
        return []

    CARDINAL = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    DIAGONAL  = [(1, 1), (1, -1), (-1, 1), (-1, -1)]

    def h(node):
        # Octile heuristic for 8-directional grid
        dx = abs(node[0] - goal[0])
        dy = abs(node[1] - goal[1])
        return max(dx, dy) + (1.414 - 1) * min(dx, dy)

    open_heap: list[tuple[float, tuple[int, int]]] = []
    heapq.heappush(open_heap, (h(start), start))

    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g: dict[tuple[int, int], float] = {start: 0.0}

    while open_heap:
        _, current = heapq.heappop(open_heap)

        if current == goal:
            path = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            path.reverse()
            return path

        for dc, dr in CARDINAL + DIAGONAL:
            nb = (current[0] + dc, current[1] + dr)
            if not nav_grid.is_walkable(*nb):
                continue
            step_cost = 1.0 if (dc == 0 or dr == 0) else 1.414
            # Block diagonal moves that cut through unwalkable corners
            if dc != 0 and dr != 0:
                if not nav_grid.is_walkable(current[0] + dc, current[1]) or \
                   not nav_grid.is_walkable(current[0], current[1] + dr):
                    continue
            tentative_g = g[current] + step_cost
            if tentative_g < g.get(nb, float("inf")):
                came_from[nb] = current
                g[nb] = tentative_g
                heapq.heappush(open_heap, (tentative_g + h(nb), nb))

    return []
