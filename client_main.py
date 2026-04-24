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


def main():
    parser = argparse.ArgumentParser(description="Age of Wars client")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", default=9876, type=int)
    args = parser.parse_args()

    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.FULLSCREEN)
    pygame.display.set_caption("Age of Wars — Multiplayer")
    clock = pygame.time.Clock()
    font  = pygame.font.SysFont(None, 36)

    # Show connecting screen
    screen.fill((10, 20, 40))
    msg = font.render(f"Connecting to {args.host}:{args.port}…", True, (200, 200, 200))
    screen.blit(msg, (SCREEN_WIDTH // 2 - msg.get_width() // 2,
                      SCREEN_HEIGHT // 2 - msg.get_height() // 2))
    pygame.display.flip()

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
        screen.fill((10, 20, 40))
        err = font.render(f"Connection failed: {result}", True, (200, 80, 80))
        screen.blit(err, (SCREEN_WIDTH // 2 - err.get_width() // 2,
                          SCREEN_HEIGHT // 2 - err.get_height() // 2))
        pygame.display.flip()
        time.sleep(3)
        pygame.quit()
        sys.exit(1)

    player_team, scene = result

    # Show waiting screen until first snapshot arrives
    screen.fill((10, 20, 40))
    wait_msg = font.render("Waiting for game to start…", True, (200, 200, 200))
    screen.blit(wait_msg, (SCREEN_WIDTH // 2 - wait_msg.get_width() // 2,
                            SCREEN_HEIGHT // 2 - wait_msg.get_height() // 2))
    pygame.display.flip()

    # Create client game
    from client_game import ClientGame
    game = ClientGame(screen, scene, player_team)

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

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
