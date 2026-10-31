import json
import threading
from functools import lru_cache

import firebase_admin
from firebase_admin import credentials, firestore

from .config import get_settings


_init_lock = threading.Lock()


@lru_cache
def init_app() -> firebase_admin.App:
    # lru_cache alone isn't enough: two threads arriving at once would both initialise
    with _init_lock:
        try:
            return firebase_admin.get_app()
        except ValueError:
            pass
        return _initialize()


def _initialize() -> firebase_admin.App:
    s = get_settings()
    if s.firebase_service_account_json:
        cred = credentials.Certificate(json.loads(s.firebase_service_account_json))
    elif s.google_application_credentials:
        cred = credentials.Certificate(s.google_application_credentials)
    else:
        cred = credentials.ApplicationDefault()
    return firebase_admin.initialize_app(cred)


def db():
    init_app()
    return firestore.client()


def user_doc():
    """users/{JARVIS_UID}"""
    return db().document(f"users/{get_settings().jarvis_uid}")


def col(name: str):
    """users/{JARVIS_UID}/{name}"""
    return user_doc().collection(name)
