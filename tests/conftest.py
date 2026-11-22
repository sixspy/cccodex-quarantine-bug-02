from __future__ import annotations

import io
import os
from pathlib import Path

import httpx
import pytest

from app.db import ensure_db
from app.seed import seed_if_needed


@pytest.fixture()
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    from app import config

    config.Config.DATABASE_PATH = path
    config.Config.INSTANCE_DIR = tmp_path
    ensure_db()
    seed_if_needed(str(path))
    return str(path)


class _WSGITransport(httpx.BaseTransport):
    def __init__(self, app):
        self.app = app

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        payload = request.content
        environ = {
            "REQUEST_METHOD": request.method,
            "PATH_INFO": request.url.path,
            "QUERY_STRING": request.url.query.decode("ascii"),
            "SERVER_NAME": "testserver",
            "SERVER_PORT": "80",
            "wsgi.url_scheme": "http",
            "wsgi.input": io.BytesIO(payload),
            "wsgi.errors": io.StringIO(),
            "CONTENT_LENGTH": str(len(payload)) if payload else "0",
            "CONTENT_TYPE": request.headers.get("content-type", ""),
        }
        for k, v in request.headers.items():
            key = "HTTP_" + k.upper().replace("-", "_")
            if key not in ("HTTP_CONTENT_TYPE", "HTTP_CONTENT_LENGTH"):
                environ[key] = v
        started: dict = {}
        chunks: list[bytes] = []

        def start_response(status, headers, exc_info=None):
            started["status"] = status
            started["headers"] = headers

        for chunk in self.app(environ, start_response):
            chunks.append(chunk)
        code = int(started["status"].split(" ", 1)[0])
        return httpx.Response(
            status_code=code,
            headers=started.get("headers", []),
            content=b"".join(chunks),
            request=request,
        )


class _JsonResponse(httpx.Response):
    @property
    def json(self):  # type: ignore[override]
        return super().json()


class _JsonClient(httpx.Client):
    def _build_request(self, request: httpx.Request) -> httpx.Request:
        return super()._build_request(request)

    def _send_single_request(self, request: httpx.Request) -> httpx.Response:
        resp = super()._send_single_request(request)
        resp.__class__ = _JsonResponse
        return resp

    def post_json(self, path, body=None, expect_errors=False):
        return self.post(path, json=body or {})

    def get(self, url, *args, expect_errors=False, **kwargs):
        return super().get(url, *args, **kwargs)

    def post(self, url, *args, expect_errors=False, **kwargs):
        return super().post(url, *args, **kwargs)


@pytest.fixture()
def testapp_factory(db_path):
    from app.main import create_app

    client = _JsonClient(
        transport=_WSGITransport(create_app()), base_url="http://testserver"
    )
    login = client.post("/api/login", json={"username": "admin", "password": "123456"})
    assert login.status_code == 200
    return client

