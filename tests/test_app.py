import tempfile
import unittest
from pathlib import Path

from app import APP_DIR, initial_project
from claude_tools_config.errors import NotFoundError


class InitialProjectTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        (self.root / "app").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_defaults_to_current_folder(self) -> None:
        self.assertEqual(initial_project(None, self.root), self.root)

    def test_tool_folder_is_not_a_project(self) -> None:
        self.assertIsNone(initial_project(None, APP_DIR))

    def test_relative_and_absolute_paths(self) -> None:
        self.assertEqual(initial_project("app", self.root), self.root / "app")
        self.assertEqual(initial_project(str(self.root / "app"), APP_DIR), self.root / "app")

    def test_missing_folder(self) -> None:
        with self.assertRaises(NotFoundError):
            initial_project("missing", self.root)
