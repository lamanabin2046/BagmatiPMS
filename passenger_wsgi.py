"""cPanel "Setup Python App" (Phusion Passenger) entry point.

cPanel मा Application startup file: passenger_wsgi.py, Entry point: application
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ProjectManagement.settings")

from ProjectManagement.wsgi import application  # noqa: E402,F401
