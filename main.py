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


scale = -1


def draw_button(
    screen: pygame.Surface, text: pygame.Surface, rect: pygame.Rect, button_height: int
):
    button_width = int(255 * scale)
    rect_to_draw = pygame.Rect(
        rect.center[0] - button_width // 2,
        rect.y - button_height // 4,
        button_width,
        button_height,
    )
    is_hovered = rect_to_draw.collidepoint(pygame.mouse.get_pos())

    left_clicked, _, _ = pygame.mouse.get_pressed()
    color = "white"
    if is_hovered:
        color = "#D6EFFE" if left_clicked else "#E8F4FF"

    pygame.draw.rect(
        screen,
        color,
        rect_to_draw,
        border_radius=5,
    )
    screen.blit(text, rect)


def create_buttons(title_bottom: int, button_height: int):
    button_text_size = int(36 * scale)
    button_font = pygame.font.Font(font_name, button_text_size)

    gap = int(32 * scale)
    margin = int(40 * scale)
    button_names = ("Jouer", "Tutoriel", "Calibration", "Quitter")
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


if __name__ == "__main__":
    # exampleAcquisition("98:D3:11:FE:03:67")

    pygame.init()

    fps = 60
    game_title = "Chunkymemo"

    ref_width, ref_height = 1280, 720

    is_windowed = len(sys.argv) > 1 and sys.argv[1] == "--windowed"
    width, height = ref_width, ref_height
    flags = 0

    if not is_windowed:
        info = pygame.display.Info()
        width, height = info.current_w, info.current_h
        flags = pygame.NOFRAME

    scale_x = width / ref_width
    scale_y = height / ref_height
    scale = min(width / ref_width, height / ref_height)

    # Otherwise texts and buttons look way too big
    scale = min(scale, 1.5)

    screen = pygame.display.set_mode((width, height), flags)
    pygame.display.set_caption(game_title)

    clock = pygame.time.Clock()
    font_name = pygame.font.get_default_font()

    title_size = int(72 * scale)
    title_font = pygame.font.Font(font_name, title_size)
    title = title_font.render(game_title.upper(), True, "white")
    title_rect = title.get_rect()
    title_rect.center = (width // 2, height // 5)

    button_height = int(76 * scale)
    buttons = create_buttons(title_rect.bottom, button_height)

    is_running = True
    while is_running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                is_running = False

        screen.fill("#014F84")

        screen.blit(title, title_rect)

        for text, text_rect in buttons.values():
            draw_button(screen, text, text_rect, button_height)

        pygame.display.flip()
        clock.tick(fps)

    pygame.quit()
