from claude_tools_config.dto import ItemKind, PresetOverrideDto, PresetRequest, Value
from claude_tools_config.errors import BadRequestError, NotFoundError
from claude_tools_config.presets import PresetService
from tests.fixtures import FakeHomeTestCase, read_json, write_json


def override(kind: ItemKind, item_id: str, value: Value) -> PresetOverrideDto:
    return PresetOverrideDto(kind=kind, id=item_id, value=value)


class PresetServiceTest(FakeHomeTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.presets = PresetService(self.paths, self.store)

    def test_create_persists_overrides_and_last_duplicate_wins(self) -> None:
        overrides = [
            override(ItemKind.SKILL, "tdd", Value.OFF),
            override(ItemKind.MCP, "maestro", Value.ON),
            override(ItemKind.SKILL, "tdd", Value.NAME_ONLY),
        ]

        created = self.presets.create(PresetRequest(name="  mobile ", overrides=overrides))
        stored = PresetService(self.paths, self.store).get(created.id)

        self.assertEqual(stored.name, "mobile")
        self.assertEqual(
            [(item.kind, item.id, item.value) for item in stored.overrides],
            [(ItemKind.SKILL, "tdd", Value.NAME_ONLY), (ItemKind.MCP, "maestro", Value.ON)],
        )

    def test_update_replaces_overrides(self) -> None:
        created = self.presets.create(PresetRequest(name="a", overrides=[override(ItemKind.SKILL, "tdd", Value.OFF)]))

        self.presets.update(created.id, PresetRequest(name="b", overrides=[override(ItemKind.PLUGIN, "playwright@official", Value.OFF)]))

        preset = self.presets.get(created.id)
        self.assertEqual(preset.name, "b")
        self.assertEqual([(item.id, item.value) for item in preset.overrides], [("playwright@official", Value.OFF)])

    def test_value_must_be_allowed_for_kind(self) -> None:
        with self.assertRaises(BadRequestError):
            self.presets.create(PresetRequest(name="x", overrides=[override(ItemKind.PLUGIN, "playwright@official", Value.NAME_ONLY)]))

    def test_old_selection_presets_are_skipped(self) -> None:
        write_json(self.paths.presets, {"presets": [{"id": "abc", "name": "old", "items": [{"kind": "skill", "id": "tdd"}]}]})

        self.assertEqual(self.presets.get("abc").overrides, [])

    def test_delete_and_errors(self) -> None:
        first = self.presets.create(PresetRequest(name="a", overrides=[]))

        self.presets.delete(first.id)

        self.assertEqual(self.presets.list().presets, [])
        with self.assertRaises(BadRequestError):
            self.presets.create(PresetRequest(name="   ", overrides=[]))
        with self.assertRaises(NotFoundError):
            self.presets.get("abc")


class ApplyPresetTest(FakeHomeTestCase):
    def test_apply_writes_overrides_on_top_and_reports_missing(self) -> None:
        self.service.set_value(self.project, ItemKind.SKILL, "grilling", Value.ON)
        overrides = [
            override(ItemKind.SKILL, "tdd", Value.OFF),
            override(ItemKind.MCP, "maestro", Value.OFF),
            override(ItemKind.SKILL, "missing", Value.OFF),
        ]

        result = self.service.apply_overrides(self.project, overrides)

        self.assertEqual(result.applied, 2)
        self.assertEqual([error.id for error in result.errors], ["missing"])
        self.assertEqual(self.local_settings()["skillOverrides"], {"grilling": "on", "tdd": "off"})
        self.assertEqual(read_json(self.paths.claude_json)["projects"][str(self.project)]["disabledMcpServers"], ["maestro"])
