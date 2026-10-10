import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from claude_tools_config.errors import InvalidJsonError
from claude_tools_config.store import JsonStore
from tests.fixtures import read_json, write_json


class JsonStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.clock = datetime(2026, 1, 1, 12, 0)
        self.store = JsonStore(self.root / "backups", keep_per_file=2, now=lambda: self.clock)

    def advance(self, minutes: int) -> None:
        self.clock += timedelta(minutes=minutes)

    def backups(self) -> list[Path]:
        return sorted((self.root / "backups").iterdir())

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_update_changes_only_target_key_and_keeps_newline_style(self) -> None:
        target = self.root / ".claude.json"
        write_json(target, {"a": 1, "nested": {"b": [1, 2]}, "c": "x"}, trailing_newline=False)

        self.store.update(target, lambda data: data.__setitem__("c", "y"))

        self.assertEqual(read_json(target), {"a": 1, "nested": {"b": [1, 2]}, "c": "y"})
        self.assertFalse(target.read_text().endswith("\n"))

    def test_update_creates_backup_with_previous_content(self) -> None:
        target = self.root / "settings.json"
        write_json(target, {"v": 1})

        self.store.update(target, lambda data: data.__setitem__("v", 2))

        self.assertEqual([read_json(backup) for backup in self.backups()], [{"v": 1}])

    def test_backup_at_most_once_per_interval(self) -> None:
        target = self.root / "settings.json"
        write_json(target, {"v": 0})

        self.store.update(target, lambda data: data.__setitem__("v", 1))
        self.advance(59)
        self.store.update(target, lambda data: data.__setitem__("v", 2))
        self.advance(1)
        self.store.update(target, lambda data: data.__setitem__("v", 3))

        self.assertEqual([read_json(backup) for backup in self.backups()], [{"v": 0}, {"v": 2}])

    def test_backups_are_pruned_per_file(self) -> None:
        target = self.root / "settings.json"
        write_json(target, {"v": 0})

        for value in range(1, 5):
            self.store.update(target, lambda data, value=value: data.__setitem__("v", value))
            self.advance(60)

        self.assertEqual([read_json(backup) for backup in self.backups()], [{"v": 2}, {"v": 3}])

    def test_same_named_projects_get_separate_backups(self) -> None:
        first = self.root / "a" / "app" / ".claude" / "settings.local.json"
        second = self.root / "b" / "app" / ".claude" / "settings.local.json"
        for target in (first, second):
            write_json(target, {"v": 0})

        self.store.update(first, lambda data: data.__setitem__("v", 1))
        self.store.update(second, lambda data: data.__setitem__("v", 1))

        names = [path.name for path in self.backups()]
        self.assertEqual(len({name.rsplit(".", 1)[0] for name in names}), 2)
        self.assertTrue(all(name.startswith("app-settings.local.json-") for name in names))

    def test_no_write_and_no_backup_when_nothing_changes(self) -> None:
        target = self.root / "settings.json"
        write_json(target, {"v": 1})
        before = target.stat().st_mtime_ns

        self.store.update(target, lambda data: data.__setitem__("v", 1))

        self.assertEqual(target.stat().st_mtime_ns, before)
        self.assertFalse((self.root / "backups").exists())

    def test_invalid_json_raises_and_file_is_untouched(self) -> None:
        target = self.root / "settings.json"
        target.write_text("{broken", encoding="utf-8")

        with self.assertRaises(InvalidJsonError):
            self.store.update(target, lambda data: data.__setitem__("v", 1))

        self.assertEqual(target.read_text(), "{broken")


if __name__ == "__main__":
    unittest.main()
