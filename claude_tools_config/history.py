from pathlib import Path

from .dto import ProjectDto, ProjectsDto
from .errors import InvalidJsonError
from .paths import Paths, normalize_path
from .store import JsonStore

RECENT_LIMIT = 15


def to_project(path: str) -> ProjectDto:
    return ProjectDto(path=path, name=Path(path).name or path, exists=Path(path).is_dir())


class HistoryService:
    def __init__(self, paths: Paths, store: JsonStore):
        self.paths = paths
        self.store = store

    def recent_paths(self) -> list[str]:
        try:
            data = self.store.read(self.paths.recent)
        except InvalidJsonError:
            return []
        return [str(item) for item in data.get("projects") or []]

    def push(self, project: Path) -> None:
        path = str(project)
        current = self.recent_paths()
        if current and current[0] == path:
            return
        recent = [path] + [item for item in current if normalize_path(item) != normalize_path(path)]
        self.store.write(self.paths.recent, {"projects": recent[:RECENT_LIMIT]})

    def projects(self) -> ProjectsDto:
        return ProjectsDto(recent=[to_project(path) for path in self.recent_paths()])
