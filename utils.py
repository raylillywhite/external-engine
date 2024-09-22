import logging
import requests

_LOG_LEVEL_MAP = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
    "notset": logging.NOTSET,
}

def setup_http_session(token):
    http = requests.Session()
    http.headers["Authorization"] = f"Bearer {token}"
    return http

def ok(res):
    try:
        res.raise_for_status()
    except requests.exceptions.HTTPError:
        logging.error("Response: %s", res.text)
        raise
    return res
