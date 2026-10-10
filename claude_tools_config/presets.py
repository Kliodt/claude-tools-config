import uuid
from dataclasses import asdict

from .dto import ItemKind, PresetDto, PresetOverrideDto, PresetRequest, PresetsDto, Value
from .errors import BadRequestError, NotFoundError
from .paths import Paths
from .pool import check_value
from .store import JsonObject, JsonStore

NAME_LIMIT = 80


def clean_name(raw: str) -> str:
    name = raw.strip()
    if not name:
        raise BadRequestError("Укажите название пресета")
    if len(name) > NAME_LIMIT:
        raise BadRequestError(f"Название длиннее {NAME_LIMIT} символов")
    return name


def clean_overrides(overrides: list[PresetOverrideDto]) -> list[PresetOverrideDto]:
    by_key: dict[tuple[str, str], PresetOverrideDto] = {}
    for override in overrides:
        check_value(override.kind, override.value)
        by_key[(str(override.kind), override.id)] = override
    return list(by_key.values())


def parse_stored_override(raw: JsonObject) -> PresetOverrideDto | None:
    try:
        return PresetOverrideDto(kind=ItemKind(raw["kind"]), id=str(raw["id"]), value=Value(raw["value"]))
    except (KeyError, ValueError, TypeError):
        return None


class PresetService:
    def __init__(self, paths: Paths, store: JsonStore):
        self.paths = paths
        self.store = store

    def list(self) -> PresetsDto:
        return PresetsDto(presets=self._read())

    def get(self, preset_id: str) -> PresetDto:
        preset = next((candidate for candidate in self._read() if candidate.id == preset_id), None)
        if preset is None:
            raise NotFoundError("Пресет не найден")
        return preset

    def create(self, request: PresetRequest) -> PresetDto:
        preset = PresetDto(id=uuid.uuid4().hex, name=clean_name(request.name), overrides=clean_overrides(request.overrides))
        self._write(self._read() + [preset])
        return preset

    def update(self, preset_id: str, request: PresetRequest) -> PresetDto:
        presets = self._read()
        updated = PresetDto(id=preset_id, name=clean_name(request.name), overrides=clean_overrides(request.overrides))
        for index, preset in enumerate(presets):
            if preset.id == preset_id:
                presets[index] = updated
                self._write(presets)
                return updated
        raise NotFoundError("Пресет не найден")

    def delete(self, preset_id: str) -> None:
        presets = self._read()
        remaining = [preset for preset in presets if preset.id != preset_id]
        if len(remaining) == len(presets):
            raise NotFoundError("Пресет не найден")
        self._write(remaining)

    def _read(self) -> list[PresetDto]:
        presets: list[PresetDto] = []
        for raw in self.store.read(self.paths.presets).get("presets") or []:
            overrides = [parse_stored_override(item) for item in raw.get("overrides") or []]
            presets.append(
                PresetDto(
                    id=str(raw["id"]),
                    name=str(raw["name"]),
                    overrides=[override for override in overrides if override is not None],
                )
            )
        return presets

    def _write(self, presets: list[PresetDto]) -> None:
        self.store.write(self.paths.presets, {"presets": [asdict(preset) for preset in presets]})
