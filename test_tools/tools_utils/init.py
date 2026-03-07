import os
import sys

from dotenv import load_dotenv


def init():
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, _root)
    sys.path.insert(0, os.path.join(_root, "script"))

    load_dotenv(os.path.join(_root, ".env"))
