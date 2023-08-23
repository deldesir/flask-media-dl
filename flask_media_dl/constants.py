""" Constants for the studio module. """


import json
import logging
import pathlib
from tomlkit import parse as toml_parse

from zimscraperlib.logging import getLogger

ROOT_DIR = pathlib.Path(__file__).parent
NAME = ROOT_DIR.name

VERSION = toml_parse(
    ROOT_DIR.parent.parent.joinpath(
        "pyproject.toml"
    ).read_text()
)["tool"]["poetry"]["version"]

SCRAPER = f"{NAME} {VERSION}"

CONFIG_FILE_PATH = "/etc/iiab/studio.json"

logger = getLogger(NAME, level=logging.DEBUG, file="/output/run.log")

with open(CONFIG_FILE_PATH) as fh:
    config = json.load(fh)
API_KEY = config["API_KEY"]
FIRST_RUN = config["FIRST_RUN"]


class Youtube:
    def __init__(self):
        self.build_dir = None
        self.cache_dir = None
        self.api_key = None

    def update(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


YOUTUBE = Youtube()
