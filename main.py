import platform
import sys

import matplotlib.pyplot as plt
import plux
import pygame

python_version = platform.python_version()
osDic = {
    "Darwin": f"MacOS/Intel{''.join(python_version.split('.')[:2])}",
    "Linux": "Linux64",
    "Windows": f"Win{platform.architecture()[0][:2]}_{''.join(python_version.split('.')[:2])}",
}

if sys.platform == "darwin":
    import subprocess
    from os import linesep

    p = subprocess.Popen("sw_vers", stdout=subprocess.PIPE)
    result = p.communicate()[0].decode("utf-8").split(str("\t"))[2].split(linesep)[0]
    if result.startswith("12."):
        print("macOS version is Monterrey!")
        osDic["Darwin"] = "MacOS/Intel310"

        if (sys.version_info.major, sys.version_info.minor) < (3, 10):
            print(f"Python version required is ≥ 3.10. Installed is {python_version}")
            exit(1)


# sys.path.append(f"PLUX-API-Python3/{osDic[platform.system()]}")

# plt.ion()
# fig, ax = plt.subplots()

# x = []
# y = []
# (line,) = ax.plot(x, y, color="tab:blue")


try:
    _ = plux.SignalsDev
except AttributeError:
    # Downloading the lib file directly is possible but wouldn't respect the principle of least astonishment.
    print(
        f"error: plux lib file is missing, make sure to download it at https://github.com/pluxbiosignals/python-samples/tree/master/PLUX-API-Python3/{osDic[platform.system()]}"
    )
    exit(1)


class NewDevice(plux.SignalsDev):
    def __init__(self, address: str):
        plux.SignalsDev.__init__(address)

    def onRawFrame(self, nSeq, data):
        if nSeq % (self.frequency // 10) == 0:
            # print(f"{nSeq:03} :", *data)
            x.append(len(x) + 1)
            y.append(data[0])
            print(nSeq, data[0])

            # plt.plot(x, y)
            line.set_data(x, y)
            ax.relim()
            ax.autoscale_view()
            plt.pause(0.01)

        return nSeq > self.duration * self.frequency


def exampleAcquisition(
    address: str,
    duration: int = 10,
    frequency: int = 100,
    active_ports=[5],
):  # time acquisition for each frequency
    """
    Example acquisition.
    """

    print("Démarrage")
    device = NewDevice(address)
    device.duration = duration  # Duration of acquisition in seconds.
    device.frequency = frequency  # Samples per second.

    print("start")

    # Trigger the start of the data recording: https://www.downloads.plux.info/apis/PLUX-API-Python-Docs/classplux_1_1_signals_dev.html#a028eaf160a20a53b3302d1abd95ae9f1
    device.start(device.frequency, active_ports, 16)

    print("loop")
    device.loop()  # calls device.onRawFrame until it returns True

    plt.title(f"Graphe de la force reçue par le capteur sur {duration} s")
    plt.xlabel("Temps (en s)")
    plt.ylabel("Force")
    plt.show(block=True)

    device.stop()
    device.close()


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


class State:
    def should_window_close(self) -> bool:
        return False

    def update(self):
        raise NotImplementedError("update must be overridden")

    def draw(self):
        raise NotImplementedError("draw must be overridden")


class MenuState(State):
    def __init__(self, game):
        self.font_name = pygame.font.get_default_font()
        self.title_size = int(72 * game.scale)
        self.title_font = pygame.font.Font(self.font_name, self.title_size)
        self.title = self.title_font.render(game.game_title.upper(), True, "white")
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
        self.is_running = True
        self.screen = game.screen
        self.hovered_button = ""
        self.left_clicked = False

    def should_window_close(self) -> bool:
        return not self.is_running

    def update(self):
        self.left_clicked = False
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.is_running = False
            else:
                # Note: this event checks for single click; pygame.mouse.get_pressed()
                # reports a held button, which is not the desired behavior.
                self.left_clicked = (
                    event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                )

        self.hovered_button = find_hovered_button(
            self.buttons, self.button_width, self.button_height
        )
        if not self.left_clicked:
            return

        if self.hovered_button == "Jouer":
            print("Gonna play")
        elif self.hovered_button == "Tutoriel":
            print("Gonna show the tutorial")
        elif self.hovered_button == "Quitter":
            self.is_running = False

    def draw(self):
        self.screen.blit(self.title, self.title_rect)

        for name, (text, text_rect) in self.buttons.items():
            color = "white"
            if name == self.hovered_button:
                color = "#D6EFFE" if self.left_clicked else "#E8F4FF"
            draw_button(
                self.screen,
                text,
                text_rect,
                self.button_width,
                self.button_height,
                color,
            )


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
        self.states = {"menu": MenuState(self)}
        self.current_state = self.states["menu"]

    def run(self):
        while not self.current_state.should_window_close():
            self.current_state.update()

            self.screen.fill("#014F84")
            self.current_state.draw()
            pygame.display.flip()

            self.clock.tick(self.fps)


if __name__ == "__main__":
    # exampleAcquisition("98:D3:11:FE:03:67")

    pygame.init()

    game = Game()
    game.run()

    pygame.quit()
