import platform
import sys

import matplotlib.pyplot as plt
import plux

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


x = []
y = []


class NewDevice(plux.SignalsDev):
    def __init__(self, address: str):
        plux.SignalsDev.__init__(address)

    def onRawFrame(self, nSeq, data):
        if nSeq % (self.frequency // 10) == 0:
            # print(f"{nSeq:03} :", *data)
            x.append(len(x) + 1)
            y.append(data[0])
            print(nSeq, data[0])

            plt.plot(x, y)
            plt.pause(0.05)

        return nSeq > self.duration * self.frequency


def exampleAcquisition(
    address: str,
    duration: int = 30,
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

    plt.show()

    device.stop()
    device.close()


if __name__ == "__main__":
    exampleAcquisition("98:D3:11:FE:03:67")
