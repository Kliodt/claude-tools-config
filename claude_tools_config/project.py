from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .batch import run_batch
from .dto import (
    BatchResultDto,
    ItemKind,
    PluginContentsDto,
    PresetOverrideDto,
    ProjectItemDto,
    ProjectStateDto,
    Source,
    Value,
    allowed_values,
)
from .errors import BadRequestError, NotFoundError
from .history import HistoryService
from .paths import (
    Paths,
    matching_project_keys,
    new_project_key,
    project_local_settings,
    project_shared_settings,
    project_skills,
)
from .pool import (
    DISABLED_MCP_SERVERS,
    DISABLED_MCPJSON_SERVERS,
    ENABLED_PLUGINS,
    MCP_SERVERS,
    PROJECTS,
    SKILL_OVERRIDES,
    PoolService,
    check_value,
    locked_or,
    plugin_value,
    read_skills,
    set_or_pop,
    skill_allowed_values,
    skill_value,
    toggle_in_list,
)
from .store import JsonObject, JsonStore, dict_section


@dataclass
class Resolved:
    value: Value
    source: Source


@dataclass
class ProjectFiles:
    user: JsonObject
    local: JsonObject
    shared: JsonObject


def resolve_project_path(raw: str) -> Path:
    cleaned = (raw or "").strip().strip("'\"").strip()
    if not cleaned:
        raise BadRequestError("Укажите путь к проекту")
    path = Path(cleaned).expanduser()
    if not path.is_absolute():
        raise BadRequestError(f"Нужен абсолютный путь: {raw}")
    if not path.is_dir():
        raise NotFoundError(f"Папка не найдена: {path}")
    return path


class ProjectService:
    def __init__(self, paths: Paths, store: JsonStore, pool: PoolService, history: HistoryService):
        self.paths = paths
        self.store = store
        self.pool = pool
        self.history = history

    def state(self, project: Path) -> ProjectStateDto:
        files = self._files(project)
        items = self._skill_items(project, files) + self._plugin_items(files) + self._mcp_items(project, files)
        self.history.push(project)
        return ProjectStateDto(path=str(project), name=project.name, items=items)

    def set_value(self, project: Path, kind: ItemKind, item_id: str, value: Value | None) -> None:
        if value is None:
            self.reset(project, kind, item_id)
            return
        check_value(kind, value)
        if kind == ItemKind.SKILL:
            self._set_skill(project, item_id, value)
        elif kind == ItemKind.PLUGIN:
            self._set_plugin(project, item_id, value)
        else:
            self._set_mcp(project, item_id, value)

    def apply_overrides(self, project: Path, overrides: list[PresetOverrideDto]) -> BatchResultDto:
        return run_batch(overrides, lambda override: self.set_value(project, override.kind, override.id, override.value))

    def reset(self, project: Path, kind: ItemKind, item_id: str) -> None:
        if kind == ItemKind.SKILL:
            self._update_local(project, lambda data: set_or_pop(data, SKILL_OVERRIDES, item_id, None))
        elif kind == ItemKind.PLUGIN:
            self._update_local(project, lambda data: set_or_pop(data, ENABLED_PLUGINS, item_id, None))
        else:
            self._reset_mcp(project, item_id)

    def _files(self, project: Path) -> ProjectFiles:
        return ProjectFiles(
            user=self.pool.user_settings(),
            local=self.store.read(project_local_settings(project)),
            shared=self.store.read(project_shared_settings(project)),
        )

    def _skill_items(self, project: Path, files: ProjectFiles) -> list[ProjectItemDto]:
        project_list = read_skills(project_skills(project))
        project_ids = {skill.id for skill in project_list}
        skills = {skill.id: skill for skill in project_list + self.pool.skills()}
        items: list[ProjectItemDto] = []
        for skill_id in sorted(skills):
            skill = skills[skill_id]
            resolved = self._resolve_skill(skill_id, skill_id in project_ids, files)
            if skill.locked:
                resolved = Resolved(locked_or(skill, resolved.value), resolved.source)
            items.append(self._item(ItemKind.SKILL, skill_id, resolved, skill_allowed_values(skill), locked=skill.locked))
        return items

    @staticmethod
    def _project_override(files: ProjectFiles, section: str, item_id: str, parse: Callable[[Any], Value]) -> Resolved | None:
        local = dict_section(files.local, section).get(item_id)
        if local is not None:
            return Resolved(parse(local), Source.OVERRIDE)
        shared = dict_section(files.shared, section).get(item_id)
        if shared is not None:
            return Resolved(parse(shared), Source.SETTINGS_JSON)
        return None

    def _resolve_skill(self, skill_id: str, is_project_skill: bool, files: ProjectFiles) -> Resolved:
        override = self._project_override(files, SKILL_OVERRIDES, skill_id, skill_value)
        if override is not None:
            return override
        if is_project_skill and skill_id not in dict_section(files.user, SKILL_OVERRIDES):
            return Resolved(Value.ON, Source.PROJECT_FILE)
        return Resolved(self.pool.global_skill_value(skill_id, files.user), Source.GLOBAL)

    def _plugin_items(self, files: ProjectFiles) -> list[ProjectItemDto]:
        return [
            self._item(ItemKind.PLUGIN, plugin.id, self._resolve_plugin(plugin.id, files), contents=plugin.contents())
            for plugin in self.pool.plugins()
            if plugin.installed
        ]

    def _resolve_plugin(self, plugin_id: str, files: ProjectFiles) -> Resolved:
        override = self._project_override(files, ENABLED_PLUGINS, plugin_id, plugin_value)
        if override is not None:
            return override
        return Resolved(self.pool.global_plugin_value(plugin_id, files.user), Source.GLOBAL)

    def _mcp_items(self, project: Path, files: ProjectFiles) -> list[ProjectItemDto]:
        entry = self.pool.project_entry(project)
        disabled = set(entry.disabled)
        local_disabled_json = set(files.local.get(DISABLED_MCPJSON_SERVERS) or [])
        shared_disabled_json = set(files.shared.get(DISABLED_MCPJSON_SERVERS) or [])
        local_defs = entry.servers
        resolved: dict[str, Resolved] = {}
        for name in self.pool.pooled_mcp():
            resolved[name] = Resolved(Value.OFF, Source.GLOBAL)
        for name in self.pool.user_mcp():
            resolved[name] = Resolved(Value.ON, Source.GLOBAL)
            if name in disabled:
                resolved[name] = Resolved(Value.OFF, Source.OVERRIDE)
        for name in self.pool.project_mcp_json(project):
            resolved[name] = Resolved(Value.ON, Source.PROJECT_FILE)
            if name in shared_disabled_json:
                resolved[name] = Resolved(Value.OFF, Source.SETTINGS_JSON)
            if name in local_disabled_json or name in disabled:
                resolved[name] = Resolved(Value.OFF, Source.OVERRIDE)
        for name in local_defs:
            resolved[name] = Resolved(Value.ON, Source.OVERRIDE)
            if name in disabled:
                resolved[name] = Resolved(Value.OFF, Source.OVERRIDE)
        return [self._item(ItemKind.MCP, name, value) for name, value in sorted(resolved.items())]

    @staticmethod
    def _item(
        kind: ItemKind,
        item_id: str,
        resolved: Resolved,
        values: list[Value] | None = None,
        locked: bool = False,
        contents: PluginContentsDto | None = None,
    ) -> ProjectItemDto:
        return ProjectItemDto(
            kind=kind,
            id=item_id,
            value=resolved.value,
            source=resolved.source,
            allowed_values=values or allowed_values(kind),
            locked=locked,
            contents=contents,
        )

    def _set_skill(self, project: Path, skill_id: str, value: Value) -> None:
        self.pool.check_skill_value(skill_id, value, project)
        self._update_local(project, lambda data: set_or_pop(data, SKILL_OVERRIDES, skill_id, str(value)))

    def _set_plugin(self, project: Path, plugin_id: str, value: Value) -> None:
        if not self.pool.find_plugin(plugin_id).installed:
            raise NotFoundError(f"Плагин «{plugin_id}» не установлен")
        enabled = value == Value.ON
        self._update_local(project, lambda data: set_or_pop(data, ENABLED_PLUGINS, plugin_id, enabled))

    def _set_mcp(self, project: Path, name: str, value: Value) -> None:
        enable = value == Value.ON
        user = self.pool.user_mcp()
        pooled = self.pool.pooled_mcp()
        local_defs = self.pool.project_entry(project).servers
        if name in local_defs:
            self._set_local_mcp(project, name, enable, local_defs[name], user, pooled)
        elif name in self.pool.project_mcp_json(project):
            self._update_local(project, lambda data: toggle_in_list(data, DISABLED_MCPJSON_SERVERS, name, not enable))
            if enable:
                self._update_entry(project, lambda entry: toggle_in_list(entry, DISABLED_MCP_SERVERS, name, False))
        elif name in user:
            self._update_entry(project, lambda entry: toggle_in_list(entry, DISABLED_MCP_SERVERS, name, not enable))
        elif name in pooled:
            if enable:
                definition = pooled[name]
                self._update_entry(project, lambda entry: self._add_local_mcp(entry, name, definition))
        else:
            raise NotFoundError(f"MCP-сервер «{name}» не найден")

    def _set_local_mcp(
        self, project: Path, name: str, enable: bool, definition: object, user: JsonObject, pooled: JsonObject
    ) -> None:
        if enable:
            self._update_entry(project, lambda entry: toggle_in_list(entry, DISABLED_MCP_SERVERS, name, False))
            return
        if name not in user and name not in pooled:
            self.store.update(self.paths.mcp_pool, lambda data: data.__setitem__(name, definition))

        def remove(entry: JsonObject) -> None:
            set_or_pop(entry, MCP_SERVERS, name, None)
            if name in user:
                toggle_in_list(entry, DISABLED_MCP_SERVERS, name, True)

        self._update_entry(project, remove)

    @staticmethod
    def _add_local_mcp(entry: JsonObject, name: str, definition: object) -> None:
        set_or_pop(entry, MCP_SERVERS, name, definition)
        toggle_in_list(entry, DISABLED_MCP_SERVERS, name, False)

    def _reset_mcp(self, project: Path, name: str) -> None:
        in_global_pool = name in self.pool.user_mcp() or name in self.pool.pooled_mcp()

        def reset_entry(entry: JsonObject) -> None:
            toggle_in_list(entry, DISABLED_MCP_SERVERS, name, False)
            if in_global_pool:
                set_or_pop(entry, MCP_SERVERS, name, None)

        self._update_entry(project, reset_entry)
        self._update_local(project, lambda data: toggle_in_list(data, DISABLED_MCPJSON_SERVERS, name, False))

    def _update_local(self, project: Path, mutate: Callable[[JsonObject], None]) -> None:
        self.store.update(project_local_settings(project), mutate)

    def _update_entry(self, project: Path, mutate: Callable[[JsonObject], None]) -> None:
        def apply(data: JsonObject) -> None:
            projects = dict_section(data, PROJECTS)
            keys = [key for key in matching_project_keys(projects, project) if isinstance(projects[key], dict)]
            for key in keys:
                mutate(projects[key])
            if keys:
                return
            entry: JsonObject = {}
            mutate(entry)
            if entry:
                projects[new_project_key(project)] = entry
                data[PROJECTS] = projects

        self.store.update(self.paths.claude_json, apply)
