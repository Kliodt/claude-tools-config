from claude_tools_config.batch import run_batch
from claude_tools_config.dto import ItemKind, Value
from tests.fixtures import FakeHomeTestCase, refs


class BatchTest(FakeHomeTestCase):
    def test_partial_failure_applies_the_rest_and_reports_errors(self) -> None:
        items = refs((ItemKind.SKILL, "tdd"), (ItemKind.SKILL, "missing"), (ItemKind.SKILL, "grilling"))

        result = run_batch(items, lambda item: self.service.set_value(self.project, item.kind, item.id, Value.NAME_ONLY))

        self.assertEqual(result.applied, 2)
        self.assertEqual([(error.id, error.kind) for error in result.errors], [("missing", ItemKind.SKILL)])
        self.assertEqual(self.local_settings()["skillOverrides"], {"tdd": "name-only", "grilling": "name-only"})
