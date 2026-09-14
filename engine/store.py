"""
ПРУФ · engine.store

Простое файловое хранилище JSON-документов. Без СУБД и без сети — чтобы прототип
запускался одной командой и работал в закрытом контуре.
Каталог данных: переменная окружения PRUF_DATA или <корень проекта>/data.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "pruf.store/1"

_LOCK = threading.RLock()
_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def root() -> str:
    custom = os.environ.get("PRUF_DATA")
    if custom:
        return os.path.abspath(custom)
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project, "data")


def _safe(name: str) -> str:
    cleaned = _SAFE.sub("_", str(name)).strip("._") or "item"
    return cleaned[:96]


def _dir(collection: str) -> str:
    path = os.path.join(root(), _safe(collection))
    os.makedirs(path, exist_ok=True)
    return path


def path_for(collection: str, name: str) -> str:
    return os.path.join(_dir(collection), _safe(name) + ".json")


def save(collection: str, name: str, payload: Dict[str, Any]) -> str:
    """Атомарная запись документа."""
    target = path_for(collection, name)
    temporary = target + ".tmp"
    with _LOCK:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
        os.replace(temporary, target)
    return target


def load(collection: str, name: str) -> Optional[Dict[str, Any]]:
    target = path_for(collection, name)
    if not os.path.exists(target):
        return None
    with _LOCK:
        try:
            with open(target, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (json.JSONDecodeError, OSError):
            return None


def exists(collection: str, name: str) -> bool:
    return os.path.exists(path_for(collection, name))


def delete(collection: str, name: str) -> bool:
    target = path_for(collection, name)
    with _LOCK:
        if os.path.exists(target):
            os.remove(target)
            return True
    return False


def list_names(collection: str) -> List[str]:
    folder = _dir(collection)
    return sorted(
        item[:-5] for item in os.listdir(folder)
        if item.endswith(".json") and not item.endswith(".tmp")
    )


def list_docs(collection: str, limit: int = 200) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    for name in list_names(collection)[:limit]:
        doc = load(collection, name)
        if doc is not None:
            docs.append(doc)
    return docs


def append(collection: str, name: str, item: Dict[str, Any], limit: int = 500) -> Dict[str, Any]:
    """Добавляет элемент в списочный документ (лиды, события, журнал)."""
    with _LOCK:
        document = load(collection, name) or {"schema": SCHEMA_VERSION, "items": []}
        items = document.setdefault("items", [])
        entry = dict(item)
        entry.setdefault("created_at", time.time())
        items.append(entry)
        document["items"] = items[-limit:]
        document["count"] = len(document["items"])
        save(collection, name, document)
        return entry


def read_items(collection: str, name: str) -> List[Dict[str, Any]]:
    document = load(collection, name) or {}
    items = document.get("items", [])
    return list(items) if isinstance(items, list) else []


def stats() -> Dict[str, Any]:
    base = root()
    collections: Dict[str, int] = {}
    if os.path.isdir(base):
        for entry in sorted(os.listdir(base)):
            folder = os.path.join(base, entry)
            if os.path.isdir(folder):
                collections[entry] = len([f for f in os.listdir(folder) if f.endswith(".json")])
    return {"schema": SCHEMA_VERSION, "root": base, "collections": collections}
