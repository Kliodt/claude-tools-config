import os
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


@dataclass(frozen=True)
class Paths:
    home: Path

    @property
    def claude_dir(self) -> Path:
        return self.home / ".claude"

    @property
    def claude_json(self) -> Path:
        return self.home / ".claude.json"

    @property
    def user_settings(self) -> Path:
        return self.claude_dir / "settings.json"

    @property
    def user_skills(self) -> Path:
        return self.claude_dir / "skills"

    @property
    def synced_skills(self) -> Path:
        return self.user_skills / "synced"

    @property
    def installed_plugins(self) -> Path:
        return self.claude_dir / "plugins" / "installed_plugins.json"

    @property
    def app_dir(self) -> Path:
        return self.home / ".config" / "claude-tools-config"

    @property
    def mcp_pool(self) -> Path:
        return self.app_dir / "mcp-pool.json"

    @property
    def recent(self) -> Path:
        return self.app_dir / "recent.json"

    @property
    def presets(self) -> Path:
        return self.app_dir / "presets.json"

    @property
    def backups(self) -> Path:
        return self.app_dir / "backups"


def normalize_path(value: str, flavor: ModuleType = os.path) -> str:
    return flavor.normcase(flavor.normpath(value))


def matching_project_keys(projects: dict, project: Path) -> list[str]:
    wanted = {normalize_path(str(project)), normalize_path(str(project.resolve()))}
    return [key for key in projects if normalize_path(key) in wanted]


def new_project_key(project: Path) -> str:
    resolved = project.resolve()
    if os.name == "nt":
        return resolved.as_posix()
    return str(resolved)


def project_local_settings(project: Path) -> Path:
    return project / ".claude" / "settings.local.json"


def project_shared_settings(project: Path) -> Path:
    return project / ".claude" / "settings.json"


def project_skills(project: Path) -> Path:
    return project / ".claude" / "skills"


def project_mcp_json(project: Path) -> Path:
    return project / ".mcp.json"
