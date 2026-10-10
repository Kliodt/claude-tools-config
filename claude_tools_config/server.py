import json
import re
import traceback
from contextlib import AbstractContextManager, nullcontext
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .batch import run_batch
from .dto import (
    BatchValueRequest,
    ErrorDto,
    ItemKind,
    ItemRefDto,
    PresetOverrideDto,
    PresetRequest,
    SetValueRequest,
    Value,
)
from .errors import AppError, BadRequestError, NotFoundError
from .history import HistoryService
from .paths import Paths
from .pool import PoolService
from .presets import PresetService
from .project import ProjectService, resolve_project_path
from .store import JsonStore

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
API_HEADER = "X-Claude-Tools-Config"
ITEM_ROUTE = re.compile(r"^/api/(global|project|items)/(skill|plugin|mcp)/(.+)$")
PRESET_ROUTE = re.compile(r"^/api/presets/([0-9a-f]+)(?:/(apply))?$")
STATIC_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}


class Services:
    def __init__(self, paths: Paths):
        self.store = JsonStore(paths.backups)
        self.history = HistoryService(paths, self.store)
        self.pool = PoolService(paths, self.store)
        self.project = ProjectService(paths, self.store, self.pool, self.history)
        self.presets = PresetService(paths, self.store)
        self.write_lock = Lock()


def parse_kind(raw: str) -> ItemKind:
    try:
        return ItemKind(raw)
    except ValueError as error:
        raise BadRequestError(f"Неизвестный тип: {raw}") from error


def parse_optional_value(body: Any) -> Value | None:
    if not isinstance(body, dict) or "value" not in body:
        raise BadRequestError("Ожидается поле value")
    raw = body["value"]
    if raw is None:
        return None
    try:
        return Value(raw)
    except ValueError as error:
        raise BadRequestError(f"Неизвестное значение: {raw}") from error


def parse_value_request(body: Any) -> SetValueRequest:
    return SetValueRequest(value=parse_optional_value(body))


def parse_item_refs(body: Any) -> list[ItemRefDto]:
    if not isinstance(body, dict) or not isinstance(body.get("items"), list):
        raise BadRequestError("Ожидается JSON {\"items\": [{\"kind\": ..., \"id\": ...}]}")
    refs: list[ItemRefDto] = []
    for raw in body["items"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            raise BadRequestError("Каждый элемент items должен содержать kind и id")
        refs.append(ItemRefDto(kind=parse_kind(str(raw.get("kind"))), id=raw["id"]))
    return refs


def parse_batch_value(body: Any) -> BatchValueRequest:
    return BatchValueRequest(items=parse_item_refs(body), value=parse_optional_value(body))


def parse_preset_request(body: Any) -> PresetRequest:
    if not isinstance(body, dict) or not isinstance(body.get("name"), str) or not isinstance(body.get("overrides"), list):
        raise BadRequestError("Ожидается JSON {\"name\": ..., \"overrides\": [{\"kind\", \"id\", \"value\"}]}")
    overrides: list[PresetOverrideDto] = []
    for raw in body["overrides"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            raise BadRequestError("Каждое переопределение должно содержать kind, id и value")
        value = parse_optional_value(raw)
        if value is None:
            raise BadRequestError("Значение переопределения не может быть null")
        overrides.append(PresetOverrideDto(kind=parse_kind(str(raw.get("kind"))), id=raw["id"], value=value))
    return PresetRequest(name=body["name"], overrides=overrides)


def make_handler(services: Services) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def do_PUT(self) -> None:
            self._dispatch("PUT")

        def do_DELETE(self) -> None:
            self._dispatch("DELETE")

        def _dispatch(self, method: str) -> None:
            url = urlparse(self.path)
            if not url.path.startswith("/api/"):
                if method == "GET":
                    self._static(url.path)
                    return
                self._error(NotFoundError("Не найдено"))
                return
            try:
                self._check_request()
                with self._lock_for(method):
                    result = self._route(method, url.path, parse_qs(url.query))
                if result is None:
                    self._send(HTTPStatus.NO_CONTENT, None)
                else:
                    self._send(HTTPStatus.OK, asdict(result))
            except AppError as error:
                self._error(error)
            except Exception:
                traceback.print_exc()
                self._error(AppError("Внутренняя ошибка сервера, подробности в терминале"))

        @staticmethod
        def _lock_for(method: str) -> AbstractContextManager[Any]:
            if method == "GET":
                return nullcontext()
            return services.write_lock

        def _check_request(self) -> None:
            port = self.server.server_address[1]
            allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in allowed_hosts or self.headers.get(API_HEADER) != "1":
                raise BadRequestError("Запрос отклонён")

        def _route(self, method: str, path: str, query: dict[str, list[str]]) -> Any:
            if method == "POST" and path == "/api/shutdown":
                self._shutdown()
                return None
            if method == "GET" and path == "/api/projects":
                return services.history.projects()
            if method == "GET" and path == "/api/global":
                return services.pool.pool()
            if method == "GET" and path == "/api/project":
                return services.project.state(self._project(query))
            if path == "/api/presets" or path.startswith("/api/presets/"):
                return self._route_presets(method, path, query)
            if method == "PUT" and path == "/api/global/batch":
                request = parse_batch_value(self._body())
                return run_batch(request.items, lambda item: services.pool.set_global(item.kind, item.id, request.value))
            if method == "PUT" and path == "/api/project/batch":
                project = self._project(query)
                request = parse_batch_value(self._body())
                return run_batch(
                    request.items,
                    lambda item: services.project.set_value(project, item.kind, item.id, request.value),
                )
            match = ITEM_ROUTE.match(path)
            if match is None:
                raise NotFoundError(f"Нет маршрута {method} {path}")
            scope, kind_raw, item_raw = match.groups()
            kind = parse_kind(kind_raw)
            item_id = unquote(item_raw)
            if scope == "items" and method == "GET":
                project = self._project(query) if query.get("path") else None
                return services.pool.detail(kind, item_id, project)
            if scope == "global" and method == "PUT":
                services.pool.set_global(kind, item_id, parse_value_request(self._body()).value)
                return None
            if scope == "project" and method == "PUT":
                services.project.set_value(self._project(query), kind, item_id, parse_value_request(self._body()).value)
                return None
            raise NotFoundError(f"Нет маршрута {method} {path}")

        def _route_presets(self, method: str, path: str, query: dict[str, list[str]]) -> Any:
            if path == "/api/presets":
                if method == "GET":
                    return services.presets.list()
                if method == "POST":
                    return services.presets.create(parse_preset_request(self._body()))
                raise NotFoundError(f"Нет маршрута {method} {path}")
            match = PRESET_ROUTE.match(path)
            if match is None:
                raise NotFoundError(f"Нет маршрута {method} {path}")
            preset_id, action = match.groups()
            if action == "apply" and method == "POST":
                return services.project.apply_overrides(self._project(query), services.presets.get(preset_id).overrides)
            if action is not None:
                raise NotFoundError(f"Нет маршрута {method} {path}")
            if method == "PUT":
                return services.presets.update(preset_id, parse_preset_request(self._body()))
            if method == "DELETE":
                services.presets.delete(preset_id)
                return None
            raise NotFoundError(f"Нет маршрута {method} {path}")

        def _shutdown(self) -> None:
            def stop() -> None:
                with services.write_lock:
                    print("Claude Tools Config: остановлен из веб-интерфейса")
                    self.server.shutdown()

            Thread(target=stop, daemon=True).start()

        def _project(self, query: dict[str, list[str]]) -> Path:
            return resolve_project_path((query.get("path") or [""])[0])

        def _body(self) -> Any:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                return json.loads(raw or b"null")
            except json.JSONDecodeError as error:
                raise BadRequestError("Тело запроса не JSON") from error

        def _static(self, path: str) -> None:
            name = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (STATIC_DIR / name).resolve()
            if STATIC_DIR not in target.parents or not target.is_file():
                self._send_bytes(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")
                return
            content_type = STATIC_CONTENT_TYPES.get(target.suffix, "application/octet-stream")
            self._send_bytes(HTTPStatus.OK, target.read_bytes(), content_type)

        def _error(self, error: AppError) -> None:
            self._send(HTTPStatus(error.status), asdict(ErrorDto(code=error.code, message=error.message)))

        def _send(self, status: HTTPStatus, payload: Any) -> None:
            if payload is None:
                self.send_response(status)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send_bytes(status, body, "application/json; charset=utf-8")

        def _send_bytes(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def create_server(paths: Paths, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(Services(paths)))
