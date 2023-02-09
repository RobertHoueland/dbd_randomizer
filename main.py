# Dead By Daylight Randomizer

import requests
import random
import requests_cache
import sys

from PyQt6.QtCore import QSize, QThread, QObject, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton,
                             QLabel, QVBoxLayout, QWidget,
                             QHBoxLayout, QProgressBar)
from PyQt6 import QtGui, QtCore

# Images from https://github.com/dearvoodoo/dbd
# Thank you to Tricky for API
MAIN_URL = 'https://dbd.tricky.lol/api/'


# GUI
class MainWindow(QMainWindow):
    # TODO: killer/survivor checkboxes and perks checkboxes
    # TODO: add images
    # Create GUI
    def __init__(self):
        super().__init__()

        # Window settings
        self.setStyleSheet("background-color: gray;")
        self.setWindowTitle("DBD Randomizer")
        self.setMinimumSize(QSize(600, 400))
        # TODO: add icon
        self.setWindowIcon(QtGui.QIcon('./UI/images/bloodpoints.png'))

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # Title label
        self.title_label = QLabel("Dead by Daylight Randomizer")
        self.title_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignHCenter)
        self.title_label.setContentsMargins(0, 25, 0, 0)
        self.title_label.setFont(QtGui.QFont(
            "Times", 20, QtGui.QFont.Weight.Bold))

        # Survivor button
        self.button_survivor = QPushButton("Generate survivor loadout")
        self.button_survivor.clicked.connect(self.button_survivor_on_click)
        self.button_survivor.setFixedWidth(200)
        self.button_survivor.setFixedHeight(50)

        # Killer button
        self.button_killer = QPushButton("Generate killer loadout")
        self.button_killer.clicked.connect(self.button_killer_on_click)
        self.button_killer.setFixedWidth(200)
        self.button_killer.setFixedHeight(50)

        # Character and perks label
        self.result_label = QLabel("")
        self.result_label.setVisible(False)
        self.result_label.setStyleSheet("font: 18px;")
        self.result_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        # Loading bar
        self.loading_bar = QProgressBar()
        self.loading_bar.setVisible(False)
        self.loading_bar.setRange(0, 0)
        self.loading_bar.setFixedHeight(50)
        self.loading_bar.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        # Assemble layout
        hbox = QHBoxLayout()
        hbox.addWidget(self.button_survivor)
        hbox.addWidget(self.button_killer)
        hbox.setSpacing(100)
        hbox.setAlignment(QtCore.Qt.AlignmentFlag.AlignBottom |
                          QtCore.Qt.AlignmentFlag.AlignHCenter)
        hbox.setContentsMargins(0, 0, 0, 25)

        vbox = QVBoxLayout()
        vbox.addWidget(self.title_label)
        vbox.addWidget(self.result_label)
        vbox.addWidget(self.loading_bar)
        vbox.addLayout(hbox)

        self.central_widget.setLayout(vbox)

    def receive_results(self, name, perks):
        if name is None or perks is None:
            self.result_label.setText('Error retrieving data')
        else:
            self.result_label.setText(name + '\n\n' + '\n'.join(perks))
        print(f"Received results: {name}, {perks}")
        return name, perks

    # Generate survivor info
    def button_survivor_on_click(self):
        self.loading_bar.setVisible(True)
        self.button_survivor.setEnabled(False)
        self.button_killer.setEnabled(False)

        # Create thread to recieve info in background
        self.thread = QThread()
        self.worker = Worker('survivor')
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.result.connect(self.thread.quit)
        self.worker.result.connect(self.worker.deleteLater)
        self.worker.result.connect(self.receive_results)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

        # Hide loading bar and show results when thread is finished
        self.thread.finished.connect(
            lambda: self.loading_bar.setVisible(False),
        )
        self.thread.finished.connect(
            lambda: self.result_label.setVisible(True),
        )
        self.thread.finished.connect(
            lambda: self.button_survivor.setEnabled(True),
        )
        self.thread.finished.connect(
            lambda: self.button_killer.setEnabled(True),
        )

    # Generate killer info

    def button_killer_on_click(self):
        self.loading_bar.setVisible(True)
        self.button_survivor.setEnabled(False)
        self.button_killer.setEnabled(False)

        # Create thread to recieve info in background
        self.thread = QThread()
        self.worker = Worker('killer')
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.result.connect(self.thread.quit)
        self.worker.result.connect(self.worker.deleteLater)
        self.worker.result.connect(self.receive_results)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

        # Hide loading bar and show results when thread is finished
        self.thread.finished.connect(
            lambda: self.loading_bar.setVisible(False),
        )
        self.thread.finished.connect(
            lambda: self.result_label.setVisible(True),
        )
        self.thread.finished.connect(
            lambda: self.button_survivor.setEnabled(True),
        )
        self.thread.finished.connect(
            lambda: self.button_killer.setEnabled(True),
        )


# Thread to run request in background
class Worker(QObject):
    result = pyqtSignal(str, list)

    def __init__(self, character):
        super().__init__()
        self.char = character

    def run(self):
        # Retrieve data
        name = get_character(self.char)
        perks = get_perks(self.char)
        self.result.emit(name, perks)


# Get index of random killer/survivor
def get_rand_char(character, num_characters):
    if character == 'survivor':
        return random.randint(0, num_characters - 1)
    elif character == 'killer':
        # this is format for killers in API, 268435456 is the first killer
        # subtrated 1 in 2nd parameter because of 0 index
        return random.randint(268435456, 268435455 + num_characters)


# Get request for killer/survivor name
def get_character(character) -> dict:
    try:
        response = requests.get(
            MAIN_URL + 'characters/?role=' + character, timeout=5)
        response.raise_for_status()

        # success
        data = response.json()
        num_characters = len(data)

        rand_num = get_rand_char(character, num_characters)
        if character == 'killer':
            # killer id needs to be string, surv id is int, api limitation
            rand_num = str(rand_num)

        # get random character name
        character = data[rand_num]['name']
        return character
    except requests.exceptions.HTTPError as errh:
        print(errh)
        return
    except requests.exceptions.ConnectionError as errc:
        print(errc)
        return
    except requests.exceptions.Timeout as errt:
        print(errt)
        return
    except requests.exceptions.RequestException as err:
        print(err)
        return


# Get request for perks and return names
def get_perks(character) -> dict:
    try:
        response = requests.get(
            MAIN_URL + 'perks?role=' + character, timeout=5)
        response.raise_for_status()

        # success
        data = response.json()
        num_perks = len(data)

        perks_data = []
        for item in data:
            perks_data.append(data[item]['name'])

        # get 4 random perks
        rand_nums = random.sample(range(0, num_perks), 4)
        perks = []
        for num in rand_nums:
            perks.append(perks_data[num])

        return perks

    except requests.exceptions.HTTPError as errh:
        print(errh)
        return
    except requests.exceptions.ConnectionError as errc:
        print(errc)
        return
    except requests.exceptions.Timeout as errt:
        print(errt)
        return
    except requests.exceptions.RequestException as err:
        print(err)
        return


def main():
    # Request cache lasts 23 hours
    requests_cache.install_cache(
        cache_name='dbd_randomizer_cache', expire_after=82800)

    # GUI
    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()

    app.exec()


if __name__ == '__main__':
    main()
