from dataclasses import dataclass, field
from enum import StrEnum


class ItemKind(StrEnum):
    SKILL = "skill"
    PLUGIN = "plugin"
    MCP = "mcp"


class Value(StrEnum):
    ON = "on"
    NAME_ONLY = "name-only"
    USER_INVOCABLE_ONLY = "user-invocable-only"
    OFF = "off"


class Source(StrEnum):
    GLOBAL = "global"
    OVERRIDE = "override"
    SETTINGS_JSON = "settings_json"
    PROJECT_FILE = "project_file"


SKILL_VALUES = [Value.ON, Value.NAME_ONLY, Value.USER_INVOCABLE_ONLY, Value.OFF]
TOGGLE_VALUES = [Value.ON, Value.OFF]


LOCKED_SKILL_VALUES = [Value.USER_INVOCABLE_ONLY, Value.OFF]


def allowed_values(kind: ItemKind) -> list[Value]:
    if kind == ItemKind.SKILL:
        return SKILL_VALUES
    return TOGGLE_VALUES


@dataclass
class PluginContentsDto:
    skills: int
    mcp: int


@dataclass
class PoolItemDto:
    kind: ItemKind
    id: str
    description: str
    value: Value
    allowed_values: list[Value]
    note: str | None = None
    locked: bool = False
    contents: PluginContentsDto | None = None


@dataclass
class PoolDto:
    skills: list[PoolItemDto]
    plugins: list[PoolItemDto]
    mcp: list[PoolItemDto]


@dataclass
class ChildDto:
    kind: ItemKind
    name: str
    description: str


@dataclass
class ConfigEntryDto:
    key: str
    value: str


@dataclass
class ItemDetailDto:
    kind: ItemKind
    id: str
    description: str
    path: str | None
    children: list[ChildDto] = field(default_factory=list)
    config: list[ConfigEntryDto] = field(default_factory=list)


@dataclass
class ProjectDto:
    path: str
    name: str
    exists: bool


@dataclass
class ProjectsDto:
    recent: list[ProjectDto]


@dataclass
class ProjectItemDto:
    kind: ItemKind
    id: str
    value: Value
    source: Source
    allowed_values: list[Value]
    locked: bool = False
    local: bool = False
    contents: PluginContentsDto | None = None


@dataclass
class ProjectStateDto:
    path: str
    name: str
    items: list[ProjectItemDto]


@dataclass
class SetValueRequest:
    value: Value | None


@dataclass
class ItemRefDto:
    kind: ItemKind
    id: str


@dataclass
class BatchValueRequest:
    items: list[ItemRefDto]
    value: Value | None


@dataclass
class BatchErrorDto:
    kind: ItemKind
    id: str
    message: str


@dataclass
class BatchResultDto:
    applied: int
    errors: list[BatchErrorDto]


@dataclass
class PresetOverrideDto:
    kind: ItemKind
    id: str
    value: Value


@dataclass
class PresetDto:
    id: str
    name: str
    overrides: list[PresetOverrideDto]


@dataclass
class PresetsDto:
    presets: list[PresetDto]


@dataclass
class PresetRequest:
    name: str
    overrides: list[PresetOverrideDto]


@dataclass
class ErrorDto:
    code: str
    message: str
