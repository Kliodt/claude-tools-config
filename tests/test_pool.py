import unittest

from claude_tools_config.dto import ItemKind, Value
from claude_tools_config.errors import BadRequestError, NotFoundError
from claude_tools_config.pool import MASK, parse_frontmatter
from tests.fixtures import FakeHomeTestCase, read_json, write_json, write_skill


class FrontmatterTest(unittest.TestCase):
    def test_folded_and_quoted_descriptions(self) -> None:
        text = "---\nname: x\ndescription: >\n  first line\n  second line\nother: 'q'\n---\nbody"
        self.assertEqual(parse_frontmatter(text), {"name": "x", "description": "first line second line", "other": "q"})

    def test_missing_frontmatter(self) -> None:
        self.assertEqual(parse_frontmatter("# Title"), {})


class PoolTest(FakeHomeTestCase):
    def test_pool_lists_all_kinds_with_global_values(self) -> None:
        pool = self.pool.pool()

        self.assertEqual({item.id: item.value for item in pool.skills}, {"grilling": Value.OFF, "tdd": Value.ON})
        self.assertEqual([(item.id, item.value) for item in pool.plugins], [("playwright@official", Value.ON)])
        self.assertEqual({item.id: item.value for item in pool.mcp}, {"jira": Value.ON, "maestro": Value.ON})

    def test_plugin_row_counts_bundled_skills_and_mcp(self) -> None:
        plugin = self.pool.pool().plugins[0]
        project_plugin = next(item for item in self.service.state(self.project).items if item.kind == ItemKind.PLUGIN)

        self.assertEqual((plugin.contents.skills, plugin.contents.mcp), (1, 1))
        self.assertEqual(project_plugin.contents, plugin.contents)

    def test_plugin_detail_includes_bundled_skills_and_mcp(self) -> None:
        detail = self.pool.detail(ItemKind.PLUGIN, "playwright@official")

        self.assertEqual({(child.kind, child.name) for child in detail.children}, {(ItemKind.SKILL, "browse"), (ItemKind.MCP, "playwright")})

    def test_synced_claude_ai_skills_are_listed_and_toggled_by_full_name(self) -> None:
        write_skill(self.paths.synced_skills / "bucket-id", "docx", "Word documents")

        skills = {item.id: item for item in self.pool.pool().skills}
        self.pool.set_global(ItemKind.SKILL, "anthropic-skills:docx", Value.OFF)

        self.assertEqual(skills["anthropic-skills:docx"].note, "claude.ai")
        self.assertNotIn("synced", skills)
        self.assertEqual(read_json(self.paths.user_settings)["skillOverrides"]["anthropic-skills:docx"], "off")
        self.assertEqual(self.pool.detail(ItemKind.SKILL, "anthropic-skills:docx").description, "Word documents")

    def test_author_locked_skill_is_user_invocable_only_and_not_editable(self) -> None:
        write_skill(self.paths.user_skills, "manual", "x", "disable-model-invocation: true")

        item = next(item for item in self.pool.pool().skills if item.id == "manual")

        self.assertTrue(item.locked)
        self.assertEqual((item.value, item.allowed_values), (Value.USER_INVOCABLE_ONLY, [Value.USER_INVOCABLE_ONLY]))
        with self.assertRaises(BadRequestError):
            self.pool.set_global(ItemKind.SKILL, "manual", Value.OFF)
        with self.assertRaises(BadRequestError):
            self.service.set_value(self.project, ItemKind.SKILL, "manual", Value.OFF)
        self.assertEqual(self.project_items()["skill:manual"], ("user-invocable-only", "global"))

    def test_plugin_in_skills_dir_is_installed(self) -> None:
        plugin_dir = self.paths.user_skills / "figma-extract"
        write_json(plugin_dir / ".claude-plugin" / "plugin.json", {"name": "figma-extract", "description": "Figma"})
        write_json(plugin_dir / ".mcp.json", {"mcpServers": {"framelink": {"command": "npx"}}})
        write_skill(plugin_dir / "skills", "figma-extract", "Extract design")

        pool = self.pool.pool()
        detail = self.pool.detail(ItemKind.PLUGIN, "figma-extract@skills-dir")

        plugin = next(item for item in pool.plugins if item.id == "figma-extract@skills-dir")
        self.assertIsNone(plugin.note)
        self.assertEqual(plugin.value, Value.OFF)
        self.assertNotIn("figma-extract", {item.id for item in pool.skills})
        self.assertEqual({(child.kind, child.name) for child in detail.children}, {(ItemKind.SKILL, "figma-extract"), (ItemKind.MCP, "framelink")})

    def test_mcp_detail_masks_secrets(self) -> None:
        detail = self.pool.detail(ItemKind.MCP, "jira")

        self.assertIn(("headers.X-Password", MASK), [(entry.key, entry.value) for entry in detail.config])
        self.assertNotIn("secret", str(detail))

    def test_global_skill_value_is_written_explicitly_even_if_default(self) -> None:
        self.pool.set_global(ItemKind.SKILL, "grilling", Value.ON)

        self.assertEqual(read_json(self.paths.user_settings)["skillOverrides"], {"grilling": "on"})
        self.assertEqual(read_json(self.paths.user_settings)["model"], "opus")

    def test_global_mcp_off_moves_definition_to_pool_and_back(self) -> None:
        self.pool.set_global(ItemKind.MCP, "maestro", Value.OFF)

        self.assertNotIn("maestro", read_json(self.paths.claude_json)["mcpServers"])
        self.assertEqual(read_json(self.paths.mcp_pool)["maestro"]["command"], "maestro")
        self.assertEqual({item.id: item.value for item in self.pool.pool().mcp}["maestro"], Value.OFF)

        self.pool.set_global(ItemKind.MCP, "maestro", Value.ON)

        self.assertEqual(read_json(self.paths.claude_json)["mcpServers"]["maestro"]["args"], ["mcp"])
        self.assertNotIn("maestro", read_json(self.paths.mcp_pool))
        self.assertEqual(read_json(self.paths.claude_json)["numStartups"], 5)

    def test_unknown_item_raises_not_found(self) -> None:
        with self.assertRaises(NotFoundError):
            self.pool.set_global(ItemKind.SKILL, "missing", Value.OFF)
