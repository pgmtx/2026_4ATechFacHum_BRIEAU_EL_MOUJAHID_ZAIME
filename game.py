import itertools
import random
import sys

import pygame

fonts = dict[int, pygame.font.Font]()


def create_text(
    label: str,
    font_size: int,
    center_x: int,
    center_y: int,
    scale: float,
    color: str = "white",
) -> tuple[pygame.Surface, pygame.Rect]:
    font_name = pygame.font.get_default_font()
    text_size = int(font_size * scale)

    # Avoids font duplicates
    if text_size not in fonts:
        fonts[text_size] = pygame.font.Font(font_name, text_size)
    text_font = fonts[text_size]

    text = text_font.render(label, True, color)
    text_rect = text.get_rect()
    text_rect.center = (center_x, center_y)
    return text, text_rect


def create_buttons(
    width: int,
    height: int,
    button_names,
    title_bottom: int,
    button_height: int,
    scale: float,
):
    button_text_size = 36

    gap = int(32 * scale)
    margin = int(40 * scale)
    total_height = len(button_names) * (button_height + gap) - gap
    start_y = (
        title_bottom + margin + (height - title_bottom - margin - total_height) // 2
    )

    buttons = {}
    for i, name in enumerate(button_names):
        buttons[name] = create_text(
            name,
            button_text_size,
            width // 2,
            start_y + i * (button_height + gap),
            scale,
            "#014F84",
        )

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
        self.states: dict[str, State] = {
            "menu": MenuState(self),
            "tutorial": TutorialState(self),
            "calibration": CalibrationState(self),
            "game": SingleArrowState(self),
            "lost": LostState(self),
            "pre_pair": PrePairState(self),
            "pair": PairArrowState(self),
        }
        self.current_state: State = self.states["menu"]

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

            # self.clock.tick(self.fps)


class State:
    def window_should_close(self) -> bool:
        return False

    def handle_events(self, events: list[pygame.event.Event]):
        pass

    def update(self):
        raise NotImplementedError("update must be overridden")

    def draw(self):
        raise NotImplementedError("draw must be overridden")


def get_title(
    game: Game, label: str, font_size: int
) -> tuple[pygame.Surface, pygame.Rect]:
    return create_text(label, font_size, game.width // 2, game.height // 5, game.scale)


class MenuState(State):
    def __init__(self, game: Game):
        self.game = game
        self.title, self.title_rect = get_title(game, game.game_title.upper(), 72)

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
            self.game.current_state = self.game.states["calibration"]
        elif self.hovered_button == "Tutoriel":
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
        self.title, self.title_rect = get_title(game, "SETUP", 64)

    def handle_events(self, events: list[pygame.event.Event]):
        pass

    def update(self):
        keys = pygame.key.get_pressed()
        if keys[pygame.K_ESCAPE]:
            self.game.current_state = self.game.states["menu"]

    def draw(self):
        self.game.screen.blit(self.title, self.title_rect)


class CalibrationState(State):
    def __init__(self, game: Game) -> None:
        self.game = game
        self.calibration_duration = 20 * 1000  # ms
        self.title, self.title_rect = get_title(game, "CALIBRATION", 64)
        self.inited = False
        self.start = 0
        self.end = 0
        bar_height = int(10 * self.game.scale)
        self.bg_rect = pygame.Rect(
            0,
            self.game.height - bar_height,
            self.game.width,
            bar_height,
        )
        self.rect = self.bg_rect.copy()

        instructions_label = "Patientez 20 secondes, les capteurs se mettent en place."
        self.instructions, self.instructions_rect = create_text(
            instructions_label, 32, game.width // 2, game.height // 2, game.scale
        )

    def update(self):
        if not self.inited:
            self.start = pygame.time.get_ticks()
            self.inited = True

        keys = pygame.key.get_pressed()
        if keys[pygame.K_SPACE]:
            self.game.current_state = self.game.states["game"]

        self.end = pygame.time.get_ticks()
        if self.end - self.start > self.calibration_duration:
            self.game.current_state = self.game.states["game"]

    def draw(self):
        pygame.draw.rect(self.game.screen, "#434c54", self.bg_rect)
        self.rect.w = (
            self.game.width * (self.end - self.start) // self.calibration_duration
        )
        pygame.draw.rect(self.game.screen, "white", self.rect)
        self.game.screen.blit(self.title, self.title_rect)
        self.game.screen.blit(self.instructions, self.instructions_rect)


directions = ("left", "up", "right", "down")
direction_keys = (pygame.K_LEFT, pygame.K_UP, pygame.K_RIGHT, pygame.K_DOWN)
# Right rotation is negative
rotations = (0, -90, 180, 90)


def get_random_direction() -> str:
    return random.choice(directions)


def get_rotation_from_direction(direction: str) -> int:
    index = directions.index(direction)
    return rotations[index]


def key_to_direction(key: int) -> str:
    index = direction_keys.index(key)
    return directions[index]


def _make_arrow_images(size: int) -> tuple[dict, dict, dict]:
    image = pygame.image.load("assets/arrow.png").convert_alpha()
    image = pygame.transform.smoothscale(image, (size, size))
    arrow_images = {
        direction: pygame.transform.rotate(image, rotation)
        for direction, rotation in zip(directions, rotations)
    }

    arrow_images_black = {}
    arrow_images_grey = {}
    for direction, surf in arrow_images.items():
        black = surf.copy()
        overlay_b = pygame.Surface(black.get_size(), pygame.SRCALPHA)
        overlay_b.fill((0, 0, 0, 255))
        black.blit(overlay_b, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        arrow_images_black[direction] = black

        grey = surf.copy()
        overlay_g = pygame.Surface(grey.get_size(), pygame.SRCALPHA)
        overlay_g.fill((150, 150, 150, 255))
        grey.blit(overlay_g, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        arrow_images_grey[direction] = grey

    return arrow_images, arrow_images_black, arrow_images_grey


def _compute_centered_x_positions(
    game_width: int, tile_size: int, count: int, margin: int, spacing: float
) -> list[int]:
    total_width = count * tile_size + max(0, count - 1) * spacing
    start_x = margin + (game_width - 2 * margin - total_width) / 2
    return [int(start_x + i * (tile_size + spacing)) for i in range(count)]


class SingleArrowState(State):
    def __init__(self, game: Game) -> None:
        self.game = game
        self.title, self.title_rect = get_title(game, "JEU", 64)
        self.arrows_count = 1
        self.arrow_directions = [get_random_direction()]

        margin = 20
        spacing_const = 40

        self.arrow_size = int(96 * game.scale)
        self.arrow_images, self.arrow_images_black, self.arrow_images_grey = (
            _make_arrow_images(self.arrow_size)
        )

        self.square_y = (game.height - self.arrow_size) // 2
        self.square_x_positions = _compute_centered_x_positions(
            game.width, self.arrow_size, self.arrows_count, margin, spacing_const
        )

        self.start = 0
        self.time_between_arrows = 500  # ms
        self.total_display_duration = self._get_display_duration()
        self.show_arrows = True
        self.arrows_to_show = 0
        self.inited = False
        self.chosen_direction = None
        self.pressed_directions = 0
        self.waiting_round_transition = False
        self.round_transition_start = 0

    def _get_display_duration(self) -> int:
        return self.time_between_arrows * (self.arrows_count + 1)

    def _compute_square_x_positions(self) -> list[int]:
        margin = 20
        spacing_const = 40
        return _compute_centered_x_positions(
            self.game.width, self.arrow_size, self.arrows_count, margin, spacing_const
        )

    def handle_events(self, events: list[pygame.event.Event]):
        if self.show_arrows or self.waiting_round_transition:
            return

        for event in events:
            if event.type != pygame.KEYDOWN:
                return
            if event.key not in direction_keys:
                self.chosen_direction = None
                return

            mapped = key_to_direction(event.key)
            print(
                f"key event: {event.key} -> {pygame.key.name(event.key)} mapped to {mapped}"
            )
            self.chosen_direction = mapped

    def update(self):
        if not self.inited:
            self.start = pygame.time.get_ticks()
            self.inited = True

        if self.show_arrows:
            self.display_arrows_progressively()
        elif self.waiting_round_transition:
            now = pygame.time.get_ticks()
            if now - self.round_transition_start >= self.time_between_arrows:
                self._start_next_round()
        else:
            self.handle_player_inputs()

    def _start_next_round(self):
        self.pressed_directions = 0
        self.arrows_count += 1
        self.arrow_directions.append(get_random_direction())
        self.inited = False
        self.chosen_direction = None
        self.show_arrows = True
        self.arrows_to_show = 0
        self.waiting_round_transition = False
        self.total_display_duration = self._get_display_duration()

    def display_arrows_progressively(self):
        end = pygame.time.get_ticks()
        elapsed = end - self.start
        print(
            f"display_progress: elapsed={elapsed} total_display_duration={self.total_display_duration} arrows_count={self.arrows_count} arrows_to_show={self.arrows_to_show}"
        )
        if elapsed > self.total_display_duration:
            print("display_progress: switching to input phase")
            self.show_arrows = False
            self.arrows_to_show = 0
            self.chosen_direction = None
        elif elapsed > self.time_between_arrows:
            i = min(elapsed // self.time_between_arrows, self.arrows_count)
            if self.arrows_to_show != i:
                self.arrows_to_show = i
                print(f"display_progress: arrows_to_show -> {self.arrows_to_show}")

    def handle_player_inputs(self):
        if self.chosen_direction is None:
            return
        expected = self.arrow_directions[self.pressed_directions]
        if self.chosen_direction != expected:
            print(
                f"MISMATCH: chosen={self.chosen_direction} expected={expected} index={self.pressed_directions} seq={self.arrow_directions}"
            )
            if len(self.arrow_directions) >= 5:
                self.game.current_state = self.game.states["pre_pair"]
            else:
                self.game.current_state = self.game.states["lost"]
            return

        self.pressed_directions += 1
        print(
            f"INPUT: correct press, pressed_directions={self.pressed_directions} arrows_count={self.arrows_count} show_arrows={self.show_arrows}"
        )
        # consume the input so it isn't processed again on the next frame
        self.chosen_direction = None

        if self.pressed_directions != len(self.arrow_directions):
            return

        # Keep the full sequence in grey for a short delay before displaying
        # the next round so the last validated input is visible.
        self.waiting_round_transition = True
        self.round_transition_start = pygame.time.get_ticks()

    def draw(self):
        self.game.screen.blit(self.title, self.title_rect)

        positions = self._compute_square_x_positions()
        if self.show_arrows:
            self.draw_display_phase(positions)
        else:
            self.draw_input_phase(positions)

    def draw_display_phase(self, positions):
        print(
            f"draw display: arrows_to_show={self.arrows_to_show} positions={len(positions)} dirs={len(self.arrow_directions)}"
        )
        it = zip(positions, self.arrow_directions)
        for idx, (x, direction) in enumerate(itertools.islice(it, self.arrows_to_show)):
            print(f"draw display: blitting idx={idx} direction={direction} at x={x}")
            self.game.screen.blit(self.arrow_images[direction], (x, self.square_y))

    def draw_input_phase(self, positions):
        print(
            f"draw input: pressed={self.pressed_directions} positions={len(positions)} dirs={len(self.arrow_directions)}"
        )
        for i, (x, direction) in enumerate(zip(positions, self.arrow_directions)):
            if i >= self.pressed_directions:
                break
            img = self.arrow_images.get(direction) or self.arrow_images_grey.get(
                direction
            )
            img = self.arrow_images_grey.get(direction, img)
            print(f"draw input: blitting grey idx={i} direction={direction} at x={x}")
            self.game.screen.blit(img, (x, self.square_y))


class LostState(State):
    def __init__(self, game: Game) -> None:
        self.game = game
        self.title, self.title_rect = get_title(game, "PERDU", 72)
        self.instructions, self.instructions_rect = create_text(
            "Appuyer sur ESPACE pour rejouer, ECHAP pour menu",
            28,
            game.width // 2,
            game.height // 2,
            game.scale,
        )

    def handle_events(self, events: list[pygame.event.Event]):
        for event in events:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    self.game.current_state = SingleArrowState(self.game)
                elif event.key == pygame.K_ESCAPE:
                    self.game.current_state = self.game.states["menu"]

    def update(self):
        pass

    def draw(self):
        self.game.screen.blit(self.title, self.title_rect)
        self.game.screen.blit(self.instructions, self.instructions_rect)


class PrePairState(State):
    def __init__(self, game: Game) -> None:
        self.game = game
        self.title, self.title_rect = get_title(game, "TRANSITION", 64)
        self.text, self.text_rect = create_text(
            "On passe aux séquences de paires. Restez concentré.",
            28,
            game.width // 2,
            game.height // 2,
            game.scale,
        )
        self.subtext, self.subtext_rect = create_text(
            "Appuyez sur [espace] pour continuer",
            20,
            game.width // 2,
            game.height * 3 // 4,
            game.scale,
        )

    def handle_events(self, events: list[pygame.event.Event]):
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                self.game.current_state = self.game.states["pair"]

    def update(self):
        pass

    def draw(self):
        self.game.screen.blit(self.title, self.title_rect)
        self.game.screen.blit(self.text, self.text_rect)
        self.game.screen.blit(self.subtext, self.subtext_rect)


class PairArrowState(State):
    def __init__(self, game: Game, initial_count: int = 1) -> None:
        self.game = game
        self.title, self.title_rect = get_title(game, "PAIR MODE", 64)

        pair_count = max(1, initial_count // 2)
        self.pair_directions = [
            (get_random_direction(), get_random_direction()) for _ in range(pair_count)
        ]

        margin = 40
        spacing = 24 * game.scale
        tile_size = int(128 * game.scale)
        self.tile_size = tile_size
        y = (game.height - tile_size) // 2
        xs = _compute_centered_x_positions(
            game.width, tile_size, pair_count, margin, spacing
        )
        self.tile_positions = [(x, y) for x in xs]

        self.arrow_size = int(48 * game.scale)
        self.arrow_images, self.arrow_images_black, self.arrow_images_grey = (
            _make_arrow_images(self.arrow_size)
        )

        self.show_pairs = True
        self.start = 0
        self.time_between_tiles = 1000
        self.tiles_to_show = 0
        self.inited = False
        self.waiting_round_transition = False
        self.round_transition_start = 0

        self.pressed_directions = 0
        self.chosen_direction = None

    # positions are computed using the shared helper _compute_centered_x_positions

    def _get_display_duration(self) -> int:
        return self.time_between_tiles * (len(self.pair_directions) + 1)

    def _start_next_round(self):
        self.pair_directions.append((get_random_direction(), get_random_direction()))
        y = (self.game.height - self.tile_size) // 2
        xs = _compute_centered_x_positions(
            self.game.width,
            self.tile_size,
            len(self.pair_directions),
            40,
            24 * self.game.scale,
        )
        self.tile_positions = [(x, y) for x in xs]
        self.pressed_directions = 0
        self.chosen_direction = None
        self.show_pairs = True
        self.start = 0
        self.tiles_to_show = 0
        self.inited = False
        self.waiting_round_transition = False
        self.round_transition_start = 0

    def handle_events(self, events: list[pygame.event.Event]):
        if self.show_pairs or self.waiting_round_transition:
            return

        for event in events:
            if event.type == pygame.KEYDOWN:
                if event.key in direction_keys:
                    self.chosen_direction = key_to_direction(event.key)
                else:
                    self.chosen_direction = None

    def update(self):
        if not self.inited:
            self.start = pygame.time.get_ticks()
            self.inited = True

        if self.show_pairs:
            end = pygame.time.get_ticks()
            if end - self.start > self._get_display_duration():
                self.show_pairs = False
                self.tiles_to_show = len(self.pair_directions)
            else:
                self.tiles_to_show = min(
                    (end - self.start) // self.time_between_tiles,
                    len(self.pair_directions),
                )
            return

        if self.waiting_round_transition:
            now = pygame.time.get_ticks()
            if now - self.round_transition_start >= 500:
                self._start_next_round()
            return

        if self.chosen_direction is None:
            return

        expected_index = self.pressed_directions
        pair_index = expected_index // 2
        sub_index = expected_index % 2
        left, right = self.pair_directions[pair_index]
        expected = left if sub_index == 0 else right
        if self.chosen_direction != expected:
            self.game.current_state = SummaryState(self.game)
            return

        self.pressed_directions += 1
        self.chosen_direction = None
        if self.pressed_directions < len(self.pair_directions) * 2:
            return

        self.waiting_round_transition = True
        self.round_transition_start = pygame.time.get_ticks()

    def draw(self):
        self.game.screen.blit(self.title, self.title_rect)

        y = (self.game.height - self.tile_size) // 2
        xs = _compute_centered_x_positions(
            self.game.width,
            self.tile_size,
            len(self.pair_directions),
            40,
            24 * self.game.scale,
        )
        positions = [(x, y) for x in xs]
        if self.show_pairs:
            self.draw_display_phase(positions)
        else:
            self.draw_input_phase(positions)

    def draw_display_phase(self, positions):
        it = zip(positions, self.pair_directions)
        for idx, (x_y, direction_pair) in enumerate(
            itertools.islice(it, self.tiles_to_show)
        ):
            (x, y) = x_y
            left, right = direction_pair
            tile_rect = pygame.Rect(x, y, self.tile_size, self.tile_size)
            pygame.draw.rect(self.game.screen, "#ffffff10", tile_rect, border_radius=8)
            lx = x + self.tile_size // 4 - self.arrow_size // 2
            rx = x + 3 * self.tile_size // 4 - self.arrow_size // 2
            self.game.screen.blit(
                self.arrow_images_black[left],
                (lx, y + (self.tile_size - self.arrow_size) // 2),
            )
            self.game.screen.blit(
                self.arrow_images_black[right],
                (rx, y + (self.tile_size - self.arrow_size) // 2),
            )

    def draw_input_phase(self, positions):
        full_tiles = self.pressed_directions // 2
        partial_arrow_visible = self.pressed_directions % 2 == 1

        for i, ((x, y), (left, right)) in enumerate(
            zip(positions, self.pair_directions)
        ):
            if i < full_tiles:
                tile_rect = pygame.Rect(x, y, self.tile_size, self.tile_size)
                pygame.draw.rect(
                    self.game.screen, "#ffffff10", tile_rect, border_radius=8
                )

                lx = x + self.tile_size // 4 - self.arrow_size // 2
                rx = x + 3 * self.tile_size // 4 - self.arrow_size // 2
                self.game.screen.blit(
                    self.arrow_images_grey[left],
                    (lx, y + (self.tile_size - self.arrow_size) // 2),
                )
                self.game.screen.blit(
                    self.arrow_images_grey[right],
                    (rx, y + (self.tile_size - self.arrow_size) // 2),
                )
                continue

            if i == full_tiles and partial_arrow_visible:
                tile_rect = pygame.Rect(x, y, self.tile_size, self.tile_size)
                pygame.draw.rect(
                    self.game.screen, "#ffffff10", tile_rect, border_radius=8
                )

                lx = x + self.tile_size // 4 - self.arrow_size // 2
                self.game.screen.blit(
                    self.arrow_images_grey[left],
                    (lx, y + (self.tile_size - self.arrow_size) // 2),
                )
            break


class SummaryState(State):
    def __init__(self, game: Game) -> None:
        self.game = game
        self.title, self.title_rect = get_title(game, "RÉSUMÉ", 64)
        self.text, self.text_rect = create_text(
            "[afficher les graphes ici]",
            28,
            game.width // 2,
            game.height // 2,
            game.scale,
        )

    def handle_events(self, events: list[pygame.event.Event]):
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.game.current_state = self.game.states["menu"]

    def update(self):
        pass

    def draw(self):
        self.game.screen.blit(self.title, self.title_rect)
        self.game.screen.blit(self.text, self.text_rect)
