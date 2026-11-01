from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from .dto import (
    ChildDto,
    ConfigEntryDto,
    ItemDetailDto,
    LOCKED_SKILL_VALUES,
    ItemKind,
    PluginContentsDto,
    PoolDto,
    PoolItemDto,
    Value,
    allowed_values,
)
from .errors import AppError, BadRequestError, NotFoundError
from .paths import Paths, matching_project_keys, project_mcp_json, project_skills
from .store import JsonObject, JsonStore, dict_section

SKILL_OVERRIDES = "skillOverrides"
ENABLED_PLUGINS = "enabledPlugins"
MCP_SERVERS = "mcpServers"
DISABLED_MCP_SERVERS = "disabledMcpServers"
DISABLED_MCPJSON_SERVERS = "disabledMcpjsonServers"
PROJECTS = "projects"
SHORT_DESCRIPTION_LIMIT = 160
MASK = "••••"
BLOCK_SCALAR_MARKERS = {"", ">", "|", ">-", "|-", ">+", "|+"}
PLUGIN_MANIFEST = Path(".claude-plugin") / "plugin.json"
SKILLS_DIR_MARKETPLACE = "skills-dir"
SYNCED_SKILLS_PREFIX = "anthropic-skills"
SYNCED_SKILLS_NOTE = "claude.ai"


class PluginScope(StrEnum):
    USER = "user"
    PROJECT = "project"
    LOCAL = "local"


@dataclass
class SkillInfo:
    id: str
    description: str
    path: Path
    note: str | None = None
    locked: bool = False


@dataclass
class ProjectEntry:
    disabled: list[str]
    servers: JsonObject


@dataclass
class PluginInfo:
    id: str
    description: str
    path: Path | None
    installed: bool
    skills: list[SkillInfo] = field(default_factory=list)
    mcp_servers: JsonObject = field(default_factory=dict)
    user_scope: bool = True
    project_scopes: dict[str, PluginScope] = field(default_factory=dict)

    def contents(self) -> PluginContentsDto:
        return PluginContentsDto(skills=len(self.skills), mcp=len(self.mcp_servers))

    def project_scope(self, project: Path) -> PluginScope | None:
        keys = matching_project_keys(self.project_scopes, project)
        if not keys:
            return None
        return self.project_scopes[keys[0]]

    def available_in(self, project: Path) -> bool:
        return self.installed and (self.user_scope or self.project_scope(project) is not None)


def parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    result: dict[str, str] = {}
    index = 1
    while index < len(lines) and lines[index].strip() != "---":
        line = lines[index]
        index += 1
        if not line or line[0].isspace() or ":" not in line:
            continue
        key, _, rest = line.partition(":")
        rest = rest.strip()
        if rest in BLOCK_SCALAR_MARKERS:
            block: list[str] = []
            while index < len(lines) and lines[index].strip() != "---" and (not lines[index] or lines[index][0].isspace()):
                block.append(lines[index].strip())
                index += 1
            rest = " ".join(part for part in block if part)
        result[key.strip()] = rest.strip().strip("'\"")
    return result


def read_skill(skill_dir: Path) -> SkillInfo | None:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return None
    meta = parse_frontmatter(skill_md.read_text(encoding="utf-8", errors="replace"))
    return SkillInfo(
        id=skill_dir.name,
        description=meta.get("description", ""),
        path=skill_md,
        locked=meta.get("disable-model-invocation", "").lower() == "true",
    )


def read_skills(directory: Path) -> list[SkillInfo]:
    if not directory.is_dir():
        return []
    skills = [read_skill(entry) for entry in sorted(directory.iterdir()) if entry.is_dir()]
    return [skill for skill in skills if skill is not None]


def read_synced_skills(directory: Path) -> list[SkillInfo]:
    if not directory.is_dir():
        return []
    return [
        replace(skill, id=f"{SYNCED_SKILLS_PREFIX}:{skill.id}", note=SYNCED_SKILLS_NOTE)
        for bucket in sorted(directory.iterdir())
        if bucket.is_dir()
        for skill in read_skills(bucket)
    ]


def short(text: str) -> str:
    if len(text) <= SHORT_DESCRIPTION_LIMIT:
        return text
    return text[: SHORT_DESCRIPTION_LIMIT - 1].rstrip() + "…"


def describe_mcp(definition: Any) -> str:
    if not isinstance(definition, dict):
        return ""
    if definition.get("url"):
        return f"{definition.get('type', 'http')} · {definition['url']}"
    command = " ".join([str(definition.get("command", ""))] + [str(arg) for arg in definition.get("args", [])])
    return f"{definition.get('type', 'stdio')} · {command.strip()}"


def mcp_config_entries(definition: Any) -> list[ConfigEntryDto]:
    if not isinstance(definition, dict):
        return []
    entries: list[ConfigEntryDto] = []
    for key, value in definition.items():
        if key in ("env", "headers") and isinstance(value, dict):
            entries.extend(ConfigEntryDto(key=f"{key}.{name}", value=MASK) for name in value)
        elif isinstance(value, list):
            entries.append(ConfigEntryDto(key=key, value=" ".join(str(item) for item in value)))
        else:
            entries.append(ConfigEntryDto(key=key, value=str(value)))
    return entries


def registry_entries(raw: Any) -> list[JsonObject]:
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [entry for entry in raw if isinstance(entry, dict)]
    return []


def registry_install_path(entries: list[JsonObject]) -> Path | None:
    for entry in entries:
        if entry.get("installPath"):
            return Path(entry["installPath"])
    return None


def registry_scope(entry: JsonObject) -> PluginScope:
    try:
        return PluginScope(entry.get("scope", PluginScope.USER))
    except ValueError:
        return PluginScope.USER


def project_scopes(entries: list[JsonObject]) -> dict[str, PluginScope]:
    return {
        str(entry["projectPath"]): registry_scope(entry)
        for entry in entries
        if registry_scope(entry) != PluginScope.USER and entry.get("projectPath")
    }


def locked_or(skill: SkillInfo, value: Value) -> Value:
    if skill.locked and value != Value.OFF:
        return Value.USER_INVOCABLE_ONLY
    return value


def skill_allowed_values(skill: SkillInfo) -> list[Value]:
    if skill.locked:
        return LOCKED_SKILL_VALUES
    return allowed_values(ItemKind.SKILL)


def skill_value(raw: Any) -> Value:
    try:
        return Value(raw)
    except ValueError:
        return Value.ON


def plugin_value(raw: Any) -> Value:
    if raw is True:
        return Value.ON
    return Value.OFF


def check_value(kind: ItemKind, value: Value) -> None:
    if value not in allowed_values(kind):
        raise BadRequestError(f"Значение «{value}» недопустимо для {kind}")


class PoolService:
    def __init__(self, paths: Paths, store: JsonStore):
        self.paths = paths
        self.store = store

    def user_settings(self) -> JsonObject:
        return self.store.read(self.paths.user_settings)

    def user_mcp(self) -> JsonObject:
        return dict_section(self.store.read(self.paths.claude_json), MCP_SERVERS)

    def pooled_mcp(self) -> JsonObject:
        return self.store.read(self.paths.mcp_pool)

    def skills(self) -> list[SkillInfo]:
        return read_skills(self.paths.user_skills) + read_synced_skills(self.paths.synced_skills)

    def find_skill(self, skill_id: str, project: Path | None = None) -> SkillInfo:
        candidates = self.skills()
        if project is not None:
            candidates = read_skills(project_skills(project)) + candidates
        skill = next((candidate for candidate in candidates if candidate.id == skill_id), None)
        if skill is None:
            raise NotFoundError(f"Скилл «{skill_id}» не найден")
        return skill

    def check_skill_value(self, skill_id: str, value: Value, project: Path | None = None) -> None:
        skill = self.find_skill(skill_id, project)
        if value not in skill_allowed_values(skill):
            raise BadRequestError(f"Скилл «{skill_id}» заблокирован автором (disable-model-invocation): допустимо только user-invocable-only или off")

    def find_plugin(self, plugin_id: str) -> PluginInfo:
        plugin = next((candidate for candidate in self.plugins() if candidate.id == plugin_id), None)
        if plugin is None:
            raise NotFoundError(f"Плагин «{plugin_id}» не найден")
        return plugin

    @staticmethod
    def global_skill_value(skill_id: str, settings: JsonObject) -> Value:
        return skill_value(dict_section(settings, SKILL_OVERRIDES).get(skill_id))

    @staticmethod
    def global_plugin_value(plugin_id: str, settings: JsonObject) -> Value:
        return plugin_value(dict_section(settings, ENABLED_PLUGINS).get(plugin_id))

    def plugins(self) -> list[PluginInfo]:
        registry = dict_section(self.store.read(self.paths.installed_plugins), "plugins")
        enabled = dict_section(self.user_settings(), ENABLED_PLUGINS)
        plugins: dict[str, PluginInfo] = {}
        for plugin_id, raw in registry.items():
            entries = registry_entries(raw)
            plugin = self._read_plugin(plugin_id, registry_install_path(entries))
            plugin.project_scopes = project_scopes(entries)
            plugin.user_scope = not plugin.project_scopes or any(registry_scope(entry) == PluginScope.USER for entry in entries)
            plugins[plugin_id] = plugin
        for plugin_dir in self._skills_dir_plugins():
            plugin_id = f"{plugin_dir.name}@{SKILLS_DIR_MARKETPLACE}"
            plugins[plugin_id] = self._read_plugin(plugin_id, plugin_dir)
        for plugin_id in enabled:
            if plugin_id not in plugins:
                plugins[plugin_id] = PluginInfo(id=plugin_id, description="", path=None, installed=False)
        return [plugins[key] for key in sorted(plugins)]

    def _skills_dir_plugins(self) -> list[Path]:
        if not self.paths.user_skills.is_dir():
            return []
        return [entry for entry in sorted(self.paths.user_skills.iterdir()) if (entry / PLUGIN_MANIFEST).is_file()]

    def _read_plugin(self, plugin_id: str, install_path: Path | None) -> PluginInfo:
        if install_path is None or not install_path.is_dir():
            return PluginInfo(id=plugin_id, description="", path=install_path, installed=False)
        manifest = self._read_optional(install_path / PLUGIN_MANIFEST)
        return PluginInfo(
            id=plugin_id,
            description=str(manifest.get("description", "")),
            path=install_path,
            installed=True,
            skills=read_skills(install_path / "skills"),
            mcp_servers=self._plugin_mcp(install_path, manifest),
        )

    def _plugin_mcp(self, install_path: Path, manifest: JsonObject) -> JsonObject:
        declared = manifest.get(MCP_SERVERS)
        if isinstance(declared, dict):
            return declared
        source = install_path / ".mcp.json"
        if isinstance(declared, str):
            source = install_path / declared
        servers = self._read_optional(source)
        if MCP_SERVERS in servers:
            return dict_section(servers, MCP_SERVERS)
        return servers

    def _read_optional(self, path: Path) -> JsonObject:
        try:
            return self.store.read(path)
        except (AppError, OSError):
            return {}

    def pool(self) -> PoolDto:
        settings = self.user_settings()
        skills = [
            PoolItemDto(
                kind=ItemKind.SKILL,
                id=skill.id,
                description=short(skill.description),
                value=locked_or(skill, self.global_skill_value(skill.id, settings)),
                allowed_values=skill_allowed_values(skill),
                note=skill.note,
                locked=skill.locked,
            )
            for skill in self.skills()
        ]
        plugins = [
            PoolItemDto(
                kind=ItemKind.PLUGIN,
                id=plugin.id,
                description=short(plugin.description),
                value=self.global_plugin_value(plugin.id, settings),
                allowed_values=allowed_values(ItemKind.PLUGIN),
                note=None if plugin.installed else "не установлен",
                contents=plugin.contents(),
            )
            for plugin in self.plugins()
            if plugin.user_scope
        ]
        mcp = [
            PoolItemDto(
                kind=ItemKind.MCP,
                id=name,
                description=short(describe_mcp(definition)),
                value=value,
                allowed_values=allowed_values(ItemKind.MCP),
            )
            for name, definition, value in self._mcp_entries()
        ]
        return PoolDto(skills=skills, plugins=plugins, mcp=mcp)

    def _mcp_entries(self) -> list[tuple[str, Any, Value]]:
        user = self.user_mcp()
        pooled = self.pooled_mcp()
        entries = [(name, definition, Value.ON) for name, definition in user.items()]
        entries += [(name, definition, Value.OFF) for name, definition in pooled.items() if name not in user]
        return sorted(entries, key=lambda entry: entry[0])

    def detail(self, kind: ItemKind, item_id: str, project: Path | None = None) -> ItemDetailDto:
        if kind == ItemKind.SKILL:
            return self._skill_detail(item_id, project)
        if kind == ItemKind.PLUGIN:
            return self._plugin_detail(item_id)
        return self._mcp_detail(item_id, project)

    def _skill_detail(self, skill_id: str, project: Path | None) -> ItemDetailDto:
        skill = self.find_skill(skill_id, project)
        return ItemDetailDto(kind=ItemKind.SKILL, id=skill.id, description=skill.description, path=str(skill.path))

    def _plugin_detail(self, plugin_id: str) -> ItemDetailDto:
        plugin = self.find_plugin(plugin_id)
        children = [ChildDto(kind=ItemKind.SKILL, name=skill.id, description=skill.description) for skill in plugin.skills]
        children += [
            ChildDto(kind=ItemKind.MCP, name=name, description=describe_mcp(definition))
            for name, definition in plugin.mcp_servers.items()
        ]
        description = plugin.description
        if not plugin.installed:
            description = "Плагин указан в enabledPlugins, но не найден в installed_plugins.json."
        return ItemDetailDto(
            kind=ItemKind.PLUGIN,
            id=plugin.id,
            description=description,
            path=str(plugin.path) if plugin.path else None,
            children=children,
        )

    def _mcp_detail(self, name: str, project: Path | None) -> ItemDetailDto:
        sources: list[tuple[JsonObject, str]] = [
            (self.user_mcp(), str(self.paths.claude_json)),
            (self.pooled_mcp(), str(self.paths.mcp_pool)),
        ]
        if project is not None:
            sources = [
                (self.project_mcp_json(project), str(project_mcp_json(project))),
                (self.project_entry(project).servers, str(self.paths.claude_json)),
            ] + sources
        for servers, path in sources:
            if name in servers:
                definition = servers[name]
                return ItemDetailDto(
                    kind=ItemKind.MCP,
                    id=name,
                    description=describe_mcp(definition),
                    path=path,
                    config=mcp_config_entries(definition),
                )
        raise NotFoundError(f"MCP-сервер «{name}» не найден")

    def project_mcp_json(self, project: Path) -> JsonObject:
        return dict_section(self.store.read(project_mcp_json(project)), MCP_SERVERS)

    def project_entry(self, project: Path) -> ProjectEntry:
        projects = dict_section(self.store.read(self.paths.claude_json), PROJECTS)
        entry = ProjectEntry(disabled=[], servers={})
        for key in matching_project_keys(projects, project):
            raw = dict_section(projects, key)
            entry.disabled += [name for name in raw.get(DISABLED_MCP_SERVERS) or [] if name not in entry.disabled]
            entry.servers.update(dict_section(raw, MCP_SERVERS))
        return entry

    def set_global(self, kind: ItemKind, item_id: str, value: Value | None) -> None:
        if value is None:
            raise BadRequestError("Для глобальной настройки value не может быть null")
        check_value(kind, value)
        if kind == ItemKind.SKILL:
            self._set_global_skill(item_id, value)
        elif kind == ItemKind.PLUGIN:
            self._set_global_plugin(item_id, value)
        else:
            self._set_global_mcp(item_id, value)

    def _set_global_skill(self, skill_id: str, value: Value) -> None:
        self.check_skill_value(skill_id, value)
        self.store.update(self.paths.user_settings, lambda data: set_or_pop(data, SKILL_OVERRIDES, skill_id, str(value)))

    def _set_global_plugin(self, plugin_id: str, value: Value) -> None:
        if not self.find_plugin(plugin_id).user_scope:
            raise BadRequestError(f"Плагин «{plugin_id}» установлен только в проектах")
        enabled = value == Value.ON
        self.store.update(self.paths.user_settings, lambda data: set_or_pop(data, ENABLED_PLUGINS, plugin_id, enabled))

    def _set_global_mcp(self, name: str, value: Value) -> None:
        user = self.user_mcp()
        pooled = self.pooled_mcp()
        if name not in user and name not in pooled:
            raise NotFoundError(f"MCP-сервер «{name}» не найден")
        if value == Value.ON and name not in user:
            definition = pooled[name]
            self.store.update(self.paths.claude_json, lambda data: set_or_pop(data, MCP_SERVERS, name, definition))
            self.store.update(self.paths.mcp_pool, lambda data: data.pop(name, None))
        elif value == Value.OFF and name in user:
            definition = user[name]
            self.store.update(self.paths.mcp_pool, lambda data: data.__setitem__(name, definition))
            self.store.update(self.paths.claude_json, lambda data: set_or_pop(data, MCP_SERVERS, name, None))


def set_or_pop(container: JsonObject, section: str, key: str, value: Any) -> None:
    current = container.get(section)
    if value is None:
        if isinstance(current, dict) and key in current:
            del current[key]
            if not current:
                del container[section]
        return
    if not isinstance(current, dict):
        current = {}
        container[section] = current
    current[key] = value


def toggle_in_list(container: JsonObject, key: str, name: str, present: bool) -> None:
    items = [item for item in container.get(key) or [] if item != name]
    if present:
        items.append(name)
    if items or key in container:
        container[key] = items
