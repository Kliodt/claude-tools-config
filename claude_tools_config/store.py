import copy
import hashlib
import json
import shutil
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .errors import InvalidJsonError

JsonObject = dict[str, Any]
STAMP_FORMAT = "%Y%m%d-%H%M%S-%f"
BACKUP_INTERVAL = timedelta(hours=1)


def dict_section(data: JsonObject, key: str) -> JsonObject:
    section = data.get(key)
    if isinstance(section, dict):
        return section
    return {}


def write_json(path: Path, data: JsonObject, trailing_newline: bool) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if trailing_newline:
        text += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def backup_prefix(path: Path) -> str:
    name = path.name.lstrip(".") or "file"
    if path.parent.name == ".claude":
        name = f"{path.parent.parent.name}-{name}"
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"{name}-{digest}"


def parse_json(text: str, path: Path) -> JsonObject:
    try:
        data = json.loads(text or "{}")
    except json.JSONDecodeError as error:
        raise InvalidJsonError(f"Невалидный JSON в {path}: {error.msg}, строка {error.lineno}") from error
    if not isinstance(data, dict):
        raise InvalidJsonError(f"В {path} ожидается JSON-объект")
    return data


class JsonStore:
    def __init__(self, backup_dir: Path, keep_per_file: int = 10, now: Callable[[], datetime] = datetime.now):
        self.backup_dir = backup_dir
        self.keep_per_file = keep_per_file
        self.now = now

    def read(self, path: Path) -> JsonObject:
        if not path.exists():
            return {}
        return parse_json(path.read_text(encoding="utf-8"), path)

    def update(self, path: Path, mutate: Callable[[JsonObject], None]) -> None:
        text = None
        if path.exists():
            text = path.read_text(encoding="utf-8")
        data = parse_json(text or "", path)
        before = copy.deepcopy(data)
        mutate(data)
        if data == before:
            return
        if text is not None:
            self._backup_if_due(path)
        write_json(path, data, trailing_newline=text is None or text.endswith("\n"))

    def write(self, path: Path, data: JsonObject) -> None:
        write_json(path, data, trailing_newline=True)

    def _backup_if_due(self, path: Path) -> None:
        prefix = backup_prefix(path)
        existing = sorted(self.backup_dir.glob(f"{prefix}.*"))
        now = self.now()
        if existing and now - backup_time(existing[-1]) < BACKUP_INTERVAL:
            return
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, self.backup_dir / f"{prefix}.{now.strftime(STAMP_FORMAT)}")
        for stale in sorted(self.backup_dir.glob(f"{prefix}.*"))[: -self.keep_per_file]:
            stale.unlink(missing_ok=True)


def backup_time(backup: Path) -> datetime:
    return datetime.strptime(backup.name.rsplit(".", 1)[1], STAMP_FORMAT)
