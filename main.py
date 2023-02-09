# Dead By Daylight Randomizer

import requests
import random
import requests_cache
import sys

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton,
                             QLabel, QLineEdit, QVBoxLayout, QWidget, QHBoxLayout)
from PyQt6 import QtWidgets, QtGui, QtCore

# Images from https://github.com/dearvoodoo/dbd
# Thank you to Tricky for API
MAIN_URL = 'https://dbd.tricky.lol/api/'


# GUI
class MainWindow(QMainWindow):
    # Create GUI
    def __init__(self):
        super().__init__()

        # Window settings
        self.setStyleSheet("background-color: gray;")
        self.setWindowTitle("DBD Randomizer")
        self.setMinimumSize(QSize(600, 400))

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

        hbox = QHBoxLayout()
        hbox.addWidget(self.button_survivor)
        hbox.addWidget(self.button_killer)
        hbox.setSpacing(100)
        hbox.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        vbox = QVBoxLayout()
        vbox.addWidget(self.title_label)
        vbox.addLayout(hbox)

        self.central_widget.setLayout(vbox)

    # Generate survivor info
    def button_survivor_on_click(self):
        name = get_character('survivor')
        perks = get_perks('survivor')
        show_results(name, perks)

    # Generate killer info
    def button_killer_on_click(self):
        name = get_character('killer')
        perks = get_perks('killer')
        show_results(name, perks)


# DEBUG: print info
def show_results(name, perks):
    # Handle errors/exceptions
    if name is None:
        print('Error getting character')
    if perks is None:
        print('Error getting perks')
        return

    # Return random results
    print('\n' + name)
    for perk in perks:
        print("    " + perk)


# Get index of random killer/survivor
def get_rand_char(character: str, num_characters) -> int:
    if character == 'survivor':
        return random.randint(0, num_characters - 1)
    elif character == 'killer':
        # this is format for killers in API, 268435456 is the first killer
        # subtrated 1 in 2nd parameter because of 0 index
        return random.randint(268435456, 268435455 + num_characters)


# Get request for killer/survivor name
def get_character(character: str) -> dict:
    try:
        response = requests.get(MAIN_URL + 'characters/?role=' + character)
        response.raise_for_status()

        # success
        data = response.json()
        num_characters = len(data)

        rand_num = get_rand_char(character, num_characters)
        if character == 'killer':
            # killer id needs to be string, surv id is int
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
def get_perks(character: str) -> dict:
    try:
        response = requests.get(MAIN_URL + 'perks?role=' + character)
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
    requests_cache.install_cache(cache_name='dbd_cache', expire_after=82800)

    # GUI
    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()

    app.exec()


if __name__ == '__main__':
    main()
