""" Utility functions for the flask-media-dl extension. """

import json
import re


def get_id_type(id):
    """
    Given a YouTube ID, returns its type (either 'playlist', 'channel_id', or 'channel_user').
    If the ID is invalid, returns None.

    :param id: YouTube ID
    :type id: str
    :return: ID type
    :rtype: str
    """
    # if id is Nonetype, return None
    if id is None:
        return None
    # if id is a string, check if it's a playlist, channel, or user
    if isinstance(id, str):
        # First, check if it's a playlist ID
        if re.match(r"^PL[-_a-zA-Z0-9]{16,}$", id):
            return "playlist"
        if re.match(r"^UC[-_a-zA-Z0-9]{22,}$", id):
            return "channel"
        if re.match(r"^[a-zA-Z0-9]+$", id):
            return "user"
        return None
    # if id is a list, check if it's a list of playlist IDs
    if isinstance(id, list):
        if all(re.match(r"^PL[-_a-zA-Z0-9]{16,}$", i) for i in id):
            return "playlist"
        return None


def check_file_type(file):
    """
    Given a file, returns its type (either 'csv' or 'txt').
    If the file is invalid, returns None.

    :param file: File
    :type file: str
    :return: File type
    :rtype: str
    """
    if file.endswith(".csv"):
        return "csv"
    elif file.endswith(".txt"):
        return "txt"
    else:
        return None


def save_json(cache_dir, key, data):
    """
    save JSON collection to path

    :param cache_dir: path to cache directory
    :type cache_dir: str
    :param key: key to save data under
    :type key: str
    :param data: data to save
    :type data: dict
    """
    with open(cache_dir.joinpath(f"{key}.json"), "w") as fp:
        json.dump(data, fp, indent=4)


def load_json(cache_dir, key):
    """load JSON collection from path or None

    :param cache_dir: path to cache directory
    :type cache_dir: str
    :param key: key to load data from
    :type key: str
    :return: data or None
    :rtype: dict
    """
    fname = cache_dir.joinpath(f"{key}.json")
    if not fname.exists():
        return None
    try:
        with open(fname) as fp:
            return json.load(fp)
    except Exception:
        return None