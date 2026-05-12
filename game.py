import sys

import pygame


def create_buttons(
    width: int,
    height: int,
    button_names,
    title_bottom: int,
    button_height: int,
    scale: float,
):
    font_name = pygame.font.get_default_font()
    button_text_size = int(36 * scale)
    button_font = pygame.font.Font(font_name, button_text_size)

    gap = int(32 * scale)
    margin = int(40 * scale)
    total_height = len(button_names) * (button_height + gap) - gap
    start_y = (
        title_bottom + margin + (height - title_bottom - margin - total_height) // 2
    )

    buttons = {}
    for i, name in enumerate(button_names):
        text = button_font.render(name, True, "#014F84")
        text_rect = text.get_rect()
        text_rect.center = (
            width // 2,
            start_y + i * (button_height + gap),
        )
        buttons[name] = (text, text_rect)

    return buttons


def find_hovered_button(buttons, button_width: int, button_height: int) -> str:
    for name, (_, text_rect) in buttons.items():
        rect = pygame.Rect(
            text_rect.center[0] - button_width // 2,
            text_rect.y - button_height // 4,
            button_width,
            button_height,
        )
        if rect.collidepoint(pygame.mouse.get_pos()):
            return name
    return ""


def draw_button(
    screen: pygame.Surface,
    text: pygame.Surface,
    rect: pygame.Rect,
    button_width: int,
    button_height: int,
    color: str,
):
    rect_to_draw = pygame.Rect(
        rect.center[0] - button_width // 2,
        rect.y - button_height // 4,
        button_width,
        button_height,
    )

    pygame.draw.rect(
        screen,
        color,
        rect_to_draw,
        border_radius=5,
    )
    screen.blit(text, rect)


class Game:
    def __init__(self):
        self.fps = 60
        self.game_title = "Chunkymemo"

        ref_width, ref_height = 1280, 720

        is_windowed = len(sys.argv) > 1 and sys.argv[1] == "--windowed"
        self.width, self.height = ref_width, ref_height
        flags = 0

        if not is_windowed:
            info = pygame.display.Info()
            self.width, self.height = info.current_w, info.current_h
            flags = pygame.NOFRAME

        scale = min(self.width / ref_width, self.height / ref_height)

        # Otherwise texts and buttons look way too big
        self.scale = min(scale, 1.5)

        self.screen = pygame.display.set_mode((self.width, self.height), flags)
        pygame.display.set_caption(self.game_title)

        self.clock = pygame.time.Clock()
        self.states = {"menu": MenuState(self), "tutorial": TutorialState(self)}
        self.current_state = self.states["menu"]

    def run(self):
        is_running = True
        while is_running and not self.current_state.window_should_close():
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    is_running = False

            self.current_state.handle_events(events)
            self.current_state.update()

            self.screen.fill("#014F84")
            self.current_state.draw()
            pygame.display.flip()

            self.clock.tick(self.fps)


class State:
    def window_should_close(self) -> bool:
        return False

    def handle_events(self, events: list[pygame.event.Event]):
        raise NotImplementedError("handle_event must be overridden")

    def update(self):
        raise NotImplementedError("update must be overridden")

    def draw(self):
        raise NotImplementedError("draw must be overridden")


class MenuState(State):
    def __init__(self, game: Game):
        self.game = game
        font_name = pygame.font.get_default_font()
        title_size = int(72 * game.scale)
        title_font = pygame.font.Font(font_name, title_size)
        self.title = title_font.render(game.game_title.upper(), True, "white")
        self.title_rect = self.title.get_rect()
        self.title_rect.center = (game.width // 2, game.height // 5)

        self.button_names = ("Jouer", "Tutoriel", "Quitter")
        self.button_width = int(255 * game.scale)
        self.button_height = int(76 * game.scale)
        self.buttons = create_buttons(
            game.width,
            game.height,
            self.button_names,
            self.title_rect.bottom,
            self.button_height,
            game.scale,
        )
        self.hovered_button = ""
        self.left_clicked = False
        self.should_close = False

    def window_should_close(self) -> bool:
        return self.should_close

    def handle_events(self, events: list[pygame.event.Event]):
        self.left_clicked = False
        for event in events:
            # Note: this event checks for single click; pygame.mouse.get_pressed()
            # reports a held button, which is not the desired behavior.
            self.left_clicked = (
                event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
            )
            if self.left_clicked:
                break

    def update(self):
        self.hovered_button = find_hovered_button(
            self.buttons, self.button_width, self.button_height
        )

        if not self.left_clicked:
            return

        if self.hovered_button == "Jouer":
            print("Gonna play")
        elif self.hovered_button == "Tutoriel":
            # print("Gonna show the tutorial")
            self.game.current_state = self.game.states["tutorial"]
        elif self.hovered_button == "Quitter":
            self.should_close = True

    def draw(self):
        self.game.screen.blit(self.title, self.title_rect)

        for name, (text, text_rect) in self.buttons.items():
            color = "white"
            if name == self.hovered_button:
                color = "#D6EFFE" if self.left_clicked else "#E8F4FF"
            draw_button(
                self.game.screen,
                text,
                text_rect,
                self.button_width,
                self.button_height,
                color,
            )


class TutorialState(State):
    def __init__(self, game: Game) -> None:
        self.game = game

        font_name = pygame.font.get_default_font()
        title_size = int(64 * game.scale)
        title_font = pygame.font.Font(font_name, title_size)
        self.title = title_font.render("SETUP", True, "white")
        self.title_rect = self.title.get_rect()
        self.title_rect.center = (game.width // 2, game.height // 5)

    def handle_events(self, events: list[pygame.event.Event]):
        pass

    def update(self):
        keys = pygame.key.get_pressed()
        if keys[pygame.K_ESCAPE]:
            self.game.current_state = self.game.states["menu"]

    def draw(self):
        self.game.screen.blit(self.title, self.title_rect)
