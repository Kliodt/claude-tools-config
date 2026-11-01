import json
import tempfile
import unittest
from pathlib import Path

from claude_tools_config import store
from claude_tools_config.dto import ItemKind, ItemRefDto
from claude_tools_config.history import HistoryService
from claude_tools_config.paths import Paths, project_local_settings
from claude_tools_config.pool import PoolService
from claude_tools_config.project import ProjectService
from claude_tools_config.store import JsonStore


def write_json(path: Path, data: dict, trailing_newline: bool = True) -> None:
    store.write_json(path, data, trailing_newline)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_skill(directory: Path, name: str, description: str, extra_frontmatter: str = "") -> None:
    skill = directory / name
    skill.mkdir(parents=True, exist_ok=True)
    frontmatter = f"name: {name}\ndescription: {description}\n{extra_frontmatter}"
    (skill / "SKILL.md").write_text(f"---\n{frontmatter.rstrip()}\n---\n\nBody\n", encoding="utf-8")


def refs(*pairs: tuple[ItemKind, str]) -> list[ItemRefDto]:
    return [ItemRefDto(kind=kind, id=item_id) for kind, item_id in pairs]


class FakeHomeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name).resolve()
        self.home = root / "home"
        self.project = root / "work" / "app"
        self.project.mkdir(parents=True)
        self.paths = Paths(home=self.home)

        write_skill(self.paths.user_skills, "tdd", "Test first")
        write_skill(self.paths.user_skills, "grilling", "Ask hard questions")
        plugin_dir = self.home / "plugin-cache" / "playwright"
        write_json(plugin_dir / ".claude-plugin" / "plugin.json", {"name": "playwright", "description": "Browser"})
        write_json(plugin_dir / ".mcp.json", {"playwright": {"command": "npx", "args": ["@playwright/mcp"]}})
        write_skill(plugin_dir / "skills", "browse", "Browse pages")
        write_json(
            self.paths.installed_plugins,
            {"version": 2, "plugins": {"playwright@official": [{"scope": "user", "installPath": str(plugin_dir)}]}},
        )
        write_json(
            self.paths.user_settings,
            {"model": "opus", "enabledPlugins": {"playwright@official": True}, "skillOverrides": {"grilling": "off"}},
        )
        write_json(
            self.paths.claude_json,
            {
                "numStartups": 5,
                "mcpServers": {
                    "maestro": {"type": "stdio", "command": "maestro", "args": ["mcp"]},
                    "jira": {"type": "http", "url": "https://jira.example/mcp", "headers": {"X-Password": "secret"}},
                },
                "projects": {str(self.project): {"allowedTools": [], "lastCost": 1.5}},
            },
            trailing_newline=False,
        )

        self.store = JsonStore(self.paths.backups)
        self.history = HistoryService(self.paths, self.store)
        self.pool = PoolService(self.paths, self.store)
        self.service = ProjectService(self.paths, self.store, self.pool, self.history)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def project_items(self) -> dict[str, tuple[str, str]]:
        state = self.service.state(self.project)
        return {f"{item.kind}:{item.id}": (str(item.value), str(item.source)) for item in state.items}

    def local_item(self, kind: ItemKind, item_id: str) -> tuple[str, str, bool]:
        item = next(item for item in self.service.state(self.project).items if item.kind == kind and item.id == item_id)
        return str(item.value), str(item.source), item.local

    def local_settings(self) -> dict:
        return read_json(project_local_settings(self.project))

    def project_entry(self) -> dict:
        return read_json(self.paths.claude_json)["projects"][str(self.project)]
