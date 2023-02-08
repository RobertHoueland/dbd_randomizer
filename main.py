# Dead By Daylight Randomizer

import requests
import random
import requests_cache

# Images from https://github.com/dearvoodoo/dbd
# Thank you to Tricky for API
MAIN_URL = 'https://dbd.tricky.lol/api/'


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
    # Expires after 23 hours
    requests_cache.install_cache(cache_name='dbd_cache', expire_after=82800)

    # CLI App
    print('Enter 0 for survivor, 1 for killer')
    choice = input()

    # Get character name and perks
    if choice == '0':
        name = get_character('survivor')
        perks = get_perks('survivor')
    elif choice == '1':
        name = get_character('killer')
        perks = get_perks('killer')
    else:
        print('Invalid input')
        return

    if name is None:
        print('Error getting character')
    if perks is None:
        print('Error getting perks')
        return

    print(name)
    for perk in perks:
        print("    " + perk)


if __name__ == '__main__':
    main()
