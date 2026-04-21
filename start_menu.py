import pygame


def run(screen: pygame.Surface) -> bool:
    """
    Show the start menu.  Returns True if the player clicked Launch Game,
    False if they closed the window.
    """
    clock  = pygame.time.Clock()
    w, h   = screen.get_size()

    BG          = (15, 12, 8)
    TITLE_COLOR = (220, 190, 120)
    BTN_IDLE    = (60, 45, 25)
    BTN_HOVER   = (100, 75, 35)
    BTN_BORDER  = (180, 140, 70)
    BTN_TEXT    = (235, 210, 150)

    title_font  = pygame.font.SysFont(None, 96)
    btn_font    = pygame.font.SysFont(None, 42)

    btn_w, btn_h = 260, 58
    btn_rect = pygame.Rect((w - btn_w) // 2, h * 2 // 3, btn_w, btn_h)

    title_surf = title_font.render("Age of Wars", True, TITLE_COLOR)
    title_rect = title_surf.get_rect(center=(w // 2, h // 3))

    while True:
        mx, my = pygame.mouse.get_pos()
        hovered = btn_rect.collidepoint(mx, my)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return False
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if hovered:
                    return True

        screen.fill(BG)
        screen.blit(title_surf, title_rect)

        pygame.draw.rect(screen, BTN_HOVER if hovered else BTN_IDLE, btn_rect, border_radius=6)
        pygame.draw.rect(screen, BTN_BORDER, btn_rect, width=2, border_radius=6)

        label = btn_font.render("Launch Game", True, BTN_TEXT)
        screen.blit(label, label.get_rect(center=btn_rect.center))

        pygame.display.flip()
        clock.tick(60)
