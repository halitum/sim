import sys

DEFAULT_BIND_HOST = "0.0.0.0" if sys.platform != "win32" else "127.0.0.1"

# api.py server
API_SERVER = {
    "host": DEFAULT_BIND_HOST,
    "port": 6010,
}