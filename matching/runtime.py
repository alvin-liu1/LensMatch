"""Application resources and per-user preferences."""
from dataclasses import fields
import json
import os
from pathlib import Path
import sys
import tempfile
import logging
from logging.handlers import RotatingFileHandler
from .models import Config

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
USER_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".config")) / "LensMatch"


def load_config(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig")) if path else {}
    if not isinstance(data, dict):
        raise ValueError("配置必须是JSON对象")
    unknown = set(data) - {f.name for f in fields(Config)}
    if unknown:
        raise ValueError("未知配置项: " + ", ".join(sorted(unknown)))
    return data


def read_preferences(path=None):
    try:
        data = json.loads(Path(path or USER_DIR / "preferences.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_preferences(data, path=None):
    target = Path(path or USER_DIR / "preferences.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
        temporary.replace(target)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def record_error(detail):
    try:
        USER_DIR.mkdir(parents=True, exist_ok=True)
        target = USER_DIR / "errors.log"
        handler = RotatingFileHandler(target, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        try:
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            handler.handle(logging.LogRecord("LensMatch", logging.ERROR, "", 0, detail, (), None))
        finally:
            handler.close()
        return target
    except OSError:
        return None
