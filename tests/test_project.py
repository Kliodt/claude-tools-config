import ntpath
from pathlib import Path

from claude_tools_config.dto import ItemKind, Value
from claude_tools_config.paths import (
    normalize_path,
    project_local_settings,
    project_mcp_json,
    project_shared_settings,
    project_skills,
)
from claude_tools_config.errors import BadRequestError, NotFoundError
from claude_tools_config.history import HistoryService
from claude_tools_config.project import resolve_project_path
from tests.fixtures import FakeHomeTestCase, read_json, write_json, write_skill


class ProjectStateTest(FakeHomeTestCase):
    def test_lists_all_items_with_inherited_values(self) -> None:
        items = self.project_items()

        self.assertEqual(items["skill:tdd"], ("on", "global"))
        self.assertEqual(items["skill:grilling"], ("off", "global"))
        self.assertEqual(items["plugin:playwright@official"], ("on", "global"))
        self.assertEqual(items["mcp:maestro"], ("on", "global"))

    def test_globally_disabled_mcp_is_listed_as_off(self) -> None:
        self.pool.set_global(ItemKind.MCP, "maestro", Value.OFF)

        self.assertEqual(self.project_items()["mcp:maestro"], ("off", "global"))

    def test_precedence_local_over_shared_over_global(self) -> None:
        write_json(project_shared_settings(self.project), {"skillOverrides": {"grilling": "name-only", "tdd": "off"}})
        write_json(project_local_settings(self.project), {"skillOverrides": {"tdd": "user-invocable-only"}})

        items = self.project_items()

        self.assertEqual(items["skill:grilling"], ("name-only", "settings_json"))
        self.assertEqual(items["skill:tdd"], ("user-invocable-only", "override"))

    def test_project_skills_and_mcp_json_are_listed(self) -> None:
        write_skill(project_skills(self.project), "deploy", "Deploy app")
        write_json(project_mcp_json(self.project), {"mcpServers": {"db": {"command": "db-mcp"}}})

        items = self.project_items()

        self.assertEqual(items["skill:deploy"], ("on", "project_file"))
        self.assertEqual(items["mcp:db"], ("on", "project_file"))

    def test_opening_project_records_history(self) -> None:
        self.service.state(self.project)

        self.assertEqual(self.history.projects().recent[0].path, str(self.project))

    def test_history_survives_restart_and_keeps_last_15(self) -> None:
        for index in range(17):
            folder = self.project.parent / f"p{index}"
            folder.mkdir()
            self.history.push(folder)

        recent = HistoryService(self.paths, self.store).projects().recent

        self.assertEqual(len(recent), 15)
        self.assertEqual(recent[0].name, "p16")


class ProjectOverrideTest(FakeHomeTestCase):
    def test_disable_inherited_skill_writes_off_and_reset_removes_it(self) -> None:
        self.service.set_value(self.project, ItemKind.SKILL, "tdd", Value.OFF)

        self.assertEqual(self.local_settings()["skillOverrides"], {"tdd": "off"})
        self.assertEqual(self.project_items()["skill:tdd"], ("off", "override"))

        self.service.reset(self.project, ItemKind.SKILL, "tdd")

        self.assertNotIn("skillOverrides", self.local_settings())

    def test_null_value_resets_override(self) -> None:
        self.service.set_value(self.project, ItemKind.PLUGIN, "playwright@official", Value.OFF)

        self.service.set_value(self.project, ItemKind.PLUGIN, "playwright@official", None)

        self.assertNotIn("enabledPlugins", self.local_settings())

    def test_enable_globally_disabled_skill_forces_on(self) -> None:
        self.service.set_value(self.project, ItemKind.SKILL, "grilling", Value.ON)

        self.assertEqual(self.local_settings()["skillOverrides"], {"grilling": "on"})
        self.assertEqual(self.project_items()["skill:grilling"], ("on", "override"))

    def test_value_equal_to_inherited_is_still_written(self) -> None:
        self.service.set_value(self.project, ItemKind.SKILL, "tdd", Value.ON)
        self.service.set_value(self.project, ItemKind.PLUGIN, "playwright@official", Value.ON)

        self.assertEqual(self.local_settings()["skillOverrides"], {"tdd": "on"})
        self.assertEqual(self.local_settings()["enabledPlugins"], {"playwright@official": True})
        self.assertEqual(self.project_items()["skill:tdd"], ("on", "override"))

    def test_disable_plugin_in_project(self) -> None:
        self.service.set_value(self.project, ItemKind.PLUGIN, "playwright@official", Value.OFF)

        self.assertEqual(self.local_settings()["enabledPlugins"], {"playwright@official": False})
        self.assertEqual(self.project_items()["plugin:playwright@official"], ("off", "override"))

    def test_disable_user_mcp_uses_disabled_list_and_keeps_entry_fields(self) -> None:
        self.service.set_value(self.project, ItemKind.MCP, "maestro", Value.OFF)

        entry = self.project_entry()
        self.assertEqual(entry["disabledMcpServers"], ["maestro"])
        self.assertEqual(entry["lastCost"], 1.5)
        self.assertEqual(self.project_items()["mcp:maestro"], ("off", "override"))

        self.service.reset(self.project, ItemKind.MCP, "maestro")

        self.assertEqual(self.project_entry()["disabledMcpServers"], [])
        self.assertEqual(self.project_items()["mcp:maestro"], ("on", "global"))

    def test_force_on_pooled_mcp_copies_definition_to_local_scope(self) -> None:
        self.pool.set_global(ItemKind.MCP, "maestro", Value.OFF)

        self.service.set_value(self.project, ItemKind.MCP, "maestro", Value.ON)

        self.assertEqual(self.project_entry()["mcpServers"]["maestro"]["command"], "maestro")
        self.assertEqual(self.project_items()["mcp:maestro"], ("on", "override"))

        self.service.set_value(self.project, ItemKind.MCP, "maestro", Value.OFF)

        self.assertNotIn("mcpServers", self.project_entry())
        self.assertIn("maestro", read_json(self.paths.mcp_pool))

    def test_local_only_mcp_is_local_and_disabled_in_place(self) -> None:
        data = read_json(self.paths.claude_json)
        data["projects"][str(self.project)]["mcpServers"] = {"own": {"command": "own-mcp"}}
        write_json(self.paths.claude_json, data)

        installed = self.local_item(ItemKind.MCP, "own")
        self.service.set_value(self.project, ItemKind.MCP, "own", Value.OFF)
        disabled = self.project_items()["mcp:own"]
        self.service.reset(self.project, ItemKind.MCP, "own")

        self.assertEqual(installed, ("on", "project_file", True))
        self.assertEqual(disabled, ("off", "override"))
        self.assertEqual(self.project_entry()["mcpServers"], {"own": {"command": "own-mcp"}})
        self.assertFalse(self.paths.mcp_pool.exists())
        self.assertEqual(self.local_item(ItemKind.MCP, "own"), ("on", "project_file", True))

    def test_plugin_installed_only_in_project_is_local(self) -> None:
        plugin_dir = self.home / "plugin-cache" / "expo"
        write_json(plugin_dir / ".claude-plugin" / "plugin.json", {"name": "expo"})
        registry = read_json(self.paths.installed_plugins)
        registry["plugins"]["expo@official"] = [{"scope": "local", "projectPath": str(self.project), "installPath": str(plugin_dir)}]
        write_json(self.paths.installed_plugins, registry)
        write_json(project_local_settings(self.project), {"enabledPlugins": {"expo@official": True}})
        other = self.project.parent / "other"
        other.mkdir()

        self.service.set_value(self.project, ItemKind.PLUGIN, "expo@official", Value.OFF)
        self.service.reset(self.project, ItemKind.PLUGIN, "expo@official")

        self.assertEqual(self.local_item(ItemKind.PLUGIN, "expo@official"), ("off", "project_file", True))
        self.assertEqual(self.local_settings()["enabledPlugins"], {"expo@official": False})
        self.assertNotIn("expo@official", {item.id for item in self.pool.pool().plugins})
        self.assertNotIn("expo@official", {item.id for item in self.service.state(other).items})
        self.assertFalse(self.local_item(ItemKind.PLUGIN, "playwright@official")[2])
        with self.assertRaises(BadRequestError):
            self.pool.set_global(ItemKind.PLUGIN, "expo@official", Value.ON)

    def test_disable_mcp_json_server_uses_local_settings(self) -> None:
        write_json(project_mcp_json(self.project), {"mcpServers": {"db": {"command": "db-mcp"}}})

        self.service.set_value(self.project, ItemKind.MCP, "db", Value.OFF)

        self.assertEqual(self.local_settings()["disabledMcpjsonServers"], ["db"])
        self.assertEqual(self.project_items()["mcp:db"], ("off", "override"))

        self.service.set_value(self.project, ItemKind.MCP, "db", Value.ON)

        self.assertEqual(self.project_items()["mcp:db"], ("on", "project_file"))

    def test_new_project_without_entry_gets_entry_only_when_needed(self) -> None:
        other = self.project.parent / "other"
        other.mkdir()

        self.service.reset(other, ItemKind.MCP, "maestro")

        self.assertNotIn(str(other), read_json(self.paths.claude_json)["projects"])

    def test_invalid_value_for_plugin(self) -> None:
        with self.assertRaises(BadRequestError):
            self.service.set_value(self.project, ItemKind.PLUGIN, "playwright@official", Value.NAME_ONLY)

    def test_unknown_skill(self) -> None:
        with self.assertRaises(NotFoundError):
            self.service.set_value(self.project, ItemKind.SKILL, "missing", Value.ON)


class ResolvePathTest(FakeHomeTestCase):
    def test_rejects_relative_and_missing(self) -> None:
        with self.assertRaises(BadRequestError):
            resolve_project_path("relative/path")
        with self.assertRaises(NotFoundError):
            resolve_project_path(str(self.project / "nope"))

    def test_strips_quotes_from_copied_path(self) -> None:
        self.assertEqual(resolve_project_path(f'  "{self.project}"  '), self.project)


class ProjectKeyVariantsTest(FakeHomeTestCase):
    def test_windows_path_variants_are_one_project(self) -> None:
        variants = [r"C:\Users\Me\App", "C:/Users/Me/App", "c:/users/me/app/", r"C:\Users\Me\App\."]

        self.assertEqual(len({normalize_path(variant, ntpath) for variant in variants}), 1)

    def test_reads_and_writes_all_duplicate_keys(self) -> None:
        data = read_json(self.paths.claude_json)
        data["projects"][str(self.project) + "/"] = {"disabledMcpServers": ["jira"]}
        write_json(self.paths.claude_json, data)

        items = self.project_items()
        self.service.set_value(self.project, ItemKind.MCP, "maestro", Value.OFF)

        self.assertEqual(items["mcp:jira"], ("off", "override"))
        projects = read_json(self.paths.claude_json)["projects"]
        self.assertEqual(projects[str(self.project)]["disabledMcpServers"], ["maestro"])
        self.assertEqual(projects[str(self.project) + "/"]["disabledMcpServers"], ["jira", "maestro"])

    def test_history_ignores_path_spelling_differences(self) -> None:
        self.history.push(Path(str(self.project) + "/"))
        self.history.push(self.project)

        self.assertEqual([project.path for project in self.history.projects().recent], [str(self.project)])

    def test_written_json_uses_lf_line_endings(self) -> None:
        self.service.set_value(self.project, ItemKind.SKILL, "tdd", Value.OFF)

        self.assertNotIn(b"\r\n", project_local_settings(self.project).read_bytes())
