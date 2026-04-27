"""
Age of Wars — game client.

Usage:
    python client_main.py [--host HOST] [--port PORT]

Connects to the server, receives GAME_START, then runs the Pygame render loop.
Network receive runs in a background thread; a queue.Queue bridges it to the
main pygame thread.
"""

import argparse
import asyncio
import queue
import sys
import threading
import time

import pygame
from pygame._sdl2.video import Window, Renderer

SCREEN_WIDTH  = 1600
SCREEN_HEIGHT = 900
FPS           = 60


def _network_thread(host: str, port: int, inbox: queue.Queue, outbox: queue.Queue,
                    start_event: threading.Event, start_result: list):
    """
    Background thread: runs the asyncio event loop for network I/O.
    Puts received messages into `inbox`; sends commands from `outbox`.
    `start_result` is set to (player_team, scene_dict) on successful connect,
    or Exception on failure.
    Reconnects with exponential backoff on connection loss.
    """
    async def run():
        from network.client import GameClient
        client = GameClient()
        try:
            player_team, scene = await client.connect(host, port)
        except Exception as e:
            start_result.append(e)
            start_event.set()
            return

        start_result.append((player_team, scene))
        start_event.set()

        backoff = 1.0

        while True:
            recv_task = asyncio.create_task(client.receive_loop(inbox.put))

            async def send_loop():
                while True:
                    await asyncio.sleep(1 / 120)
                    while not outbox.empty():
                        cmd = outbox.get_nowait()
                        await client.send_command(cmd)

            send_task = asyncio.create_task(send_loop())
            await recv_task  # returns when connection drops
            send_task.cancel()

            # Notify main thread of disconnect
            inbox.put({"type": "DISCONNECTED"})

            # Reconnect with backoff
            while True:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                try:
                    client2 = GameClient()
                    await client2.connect(host, port)
                    client = client2
                    backoff = 1.0
                    inbox.put({"type": "RECONNECTED"})
                    break
                except Exception:
                    pass

    asyncio.run(run())


def _blit_text(renderer: Renderer, font: pygame.font.Font, text: str,
               color: tuple, cx: int, cy: int) -> None:
    import texture_cache
    surf = font.render(text, True, color)
    tex  = texture_cache.make_texture(surf)
    w, h = surf.get_size()
    tex.draw(dstrect=(cx - w // 2, cy - h // 2, w, h))


def main():
    parser = argparse.ArgumentParser(description="Age of Wars client")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", default=9876, type=int)
    args = parser.parse_args()

    pygame.init()
    window   = Window("Age of Wars — Multiplayer", size=(SCREEN_WIDTH, SCREEN_HEIGHT),
                      fullscreen_desktop=True)
    renderer = Renderer(window, accelerated=1, vsync=True)
    clock    = pygame.time.Clock()
    font     = pygame.font.SysFont(None, 36)

    from camera import Viewport
    win_w, win_h = window.size
    viewport = Viewport(win_w, win_h, SCREEN_WIDTH, SCREEN_HEIGHT)

    import texture_cache
    texture_cache.init(renderer)

    # Show connecting screen
    renderer.draw_color = (10, 20, 40, 255)
    renderer.clear()
    _blit_text(renderer, font, f"Connecting to {args.host}:{args.port}…",
               (200, 200, 200), win_w // 2, win_h // 2)
    renderer.present()

    # Start network thread
    inbox:        queue.Queue = queue.Queue()
    outbox:       queue.Queue = queue.Queue()
    start_event:  threading.Event = threading.Event()
    start_result: list = []

    net_thread = threading.Thread(
        target=_network_thread,
        args=(args.host, args.port, inbox, outbox, start_event, start_result),
        daemon=True,
    )
    net_thread.start()

    # Wait for connection (with event loop to keep window responsive)
    while not start_event.is_set():
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                pygame.quit()
                sys.exit()
        clock.tick(30)

    result = start_result[0]
    if isinstance(result, Exception):
        renderer.draw_color = (10, 20, 40, 255)
        renderer.clear()
        _blit_text(renderer, font, f"Connection failed: {result}",
                   (200, 80, 80), win_w // 2, win_h // 2)
        renderer.present()
        time.sleep(3)
        pygame.quit()
        sys.exit(1)

    player_team, scene = result

    # Show waiting screen until first snapshot arrives
    renderer.draw_color = (10, 20, 40, 255)
    renderer.clear()
    _blit_text(renderer, font, "Waiting for game to start…",
               (200, 200, 200), win_w // 2, win_h // 2)
    renderer.present()

    # Create client game
    from client_game import ClientGame
    game = ClientGame(renderer, scene, player_team, viewport)

    # Main loop
    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            else:
                game.handle_event(event)

        # Drain inbox — apply all pending server messages
        while not inbox.empty():
            try:
                msg = inbox.get_nowait()
                game.apply_message(msg)
            except queue.Empty:
                break

        game.update(dt)
        game.render()

        # Drain command queue → outbox → network thread
        while not game._cmd_queue.empty():
            try:
                cmd = game._cmd_queue.get_nowait()
                outbox.put(cmd)
            except queue.Empty:
                break

        renderer.present()

    pygame.quit()


if __name__ == "__main__":
    main()
