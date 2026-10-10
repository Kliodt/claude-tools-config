import argparse
import webbrowser
from pathlib import Path

from claude_tools_config.errors import AppError
from claude_tools_config.history import HistoryService
from claude_tools_config.paths import Paths
from claude_tools_config.project import resolve_project_path
from claude_tools_config.server import create_server
from claude_tools_config.store import JsonStore

DEFAULT_PORT = 8765
APP_DIR = Path(__file__).resolve().parent


def initial_project(raw: str | None, cwd: Path) -> Path | None:
    if raw is not None:
        return resolve_project_path(str((cwd / Path(raw).expanduser()).resolve()))
    if cwd.resolve() == APP_DIR:
        return None
    return cwd.resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Code skills, plugins and MCP manager")
    parser.add_argument("project", nargs="?", help="project folder to open; default: current folder")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="0 = any free port")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    paths = Paths(home=Path.home())
    try:
        project = initial_project(args.project, Path.cwd())
    except AppError as error:
        parser.error(error.message)
    if project is not None:
        HistoryService(paths, JsonStore(paths.backups)).push(project)

    try:
        server = create_server(paths, args.port)
    except OSError:
        server = create_server(paths, 0)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Claude Tools Config: {url}  (Ctrl+C — остановить)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
