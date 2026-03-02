"""HTTP request tool — make HTTP requests to external APIs."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Literal

from pydantic import BaseModel, Field

from agentos.tools.base import BaseTool, SideEffect


# ── Schemas ────────────────────────────────────────────────────────


class HTTPRequestInput(BaseModel):
    """Input schema for HTTP requests."""

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"] = Field(
        default="GET", description="HTTP method"
    )
    url: str = Field(..., description="Request URL")
    headers: dict[str, str] = Field(
        default_factory=dict, description="Request headers"
    )
    body: str | None = Field(default=None, description="Request body (JSON string or plain text)")
    timeout: int = Field(default=30, ge=1, le=120, description="Timeout in seconds")


class HTTPRequestOutput(BaseModel):
    """Output schema for HTTP requests."""

    status_code: int = 0
    headers: dict[str, str] = Field(default_factory=dict)
    body: str = ""
    elapsed_ms: float = 0.0
    error: str | None = None


# ── Tool ───────────────────────────────────────────────────────────


class HTTPRequestTool(BaseTool):
    """Make HTTP requests to external APIs and services."""

    @property
    def name(self) -> str:
        return "http_request"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return HTTPRequestInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return HTTPRequestOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.READ

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, HTTPRequestInput)

        data = input_data.body.encode("utf-8") if input_data.body else None
        req = urllib.request.Request(
            input_data.url,
            data=data,
            headers=input_data.headers,
            method=input_data.method,
        )

        start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=input_data.timeout) as resp:
                elapsed = (time.monotonic() - start) * 1000
                body_bytes = resp.read(1_000_000)  # 1 MB max
                try:
                    body = body_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    body = f"<binary data, {len(body_bytes)} bytes>"
                resp_headers = {k: v for k, v in resp.getheaders()}
                return HTTPRequestOutput(
                    status_code=resp.status,
                    headers=resp_headers,
                    body=body[:50_000],
                    elapsed_ms=round(elapsed, 2),
                )
        except urllib.error.HTTPError as exc:
            elapsed = (time.monotonic() - start) * 1000
            try:
                err_body = exc.read(50_000).decode("utf-8", errors="replace")
            except Exception:
                err_body = ""
            return HTTPRequestOutput(
                status_code=exc.code,
                body=err_body,
                elapsed_ms=round(elapsed, 2),
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            elapsed = (time.monotonic() - start) * 1000
            return HTTPRequestOutput(
                error=f"Request failed: {exc}",
                elapsed_ms=round(elapsed, 2),
            )
