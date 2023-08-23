import unittest
from contextlib import contextmanager

import pytest
from flask import Flask

from flask_media_dl import MediaDownloader


class TestCase(unittest.TestCase):
    TESTING = True
