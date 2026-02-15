"""Slack integration tools — post and read messages."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from pydantic import BaseModel, Field

from agentos.tools.base import BaseTool, SideEffect


# ── Schemas ────────────────────────────────────────────────────────


class SlackPostInput(BaseModel):
    channel: str = Field(..., description="Slack channel ID or name (e.g. '#general')")
    text: str = Field(..., description="Message text")
    thread_ts: str = Field(default="", description="Thread timestamp for replies")


class SlackPostOutput(BaseModel):
    ok: bool = False
    ts: str = ""
    channel: str = ""
    error: str | None = None


class SlackReadInput(BaseModel):
    channel: str = Field(..., description="Slack channel ID")
    limit: int = Field(default=20, ge=1, le=100, description="Number of messages to fetch")
    oldest: str = Field(default="", description="Only messages after this timestamp")


class SlackMessage(BaseModel):
    user: str = ""
    text: str = ""
    ts: str = ""
    thread_ts: str = ""


class SlackReadOutput(BaseModel):
    messages: list[SlackMessage] = Field(default_factory=list)
    has_more: bool = False
    error: str | None = None


# ── Tools ──────────────────────────────────────────────────────────


def _slack_api(token: str, method: str, params: dict) -> dict:
    """Call a Slack Web API method using urllib."""
    url = f"https://slack.com/api/{method}"
    data = json.dumps(params).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


class SlackPostTool(BaseTool):
    """Post a message to a Slack channel."""

    def __init__(self, *, bot_token: str = "") -> None:
        self._bot_token = bot_token

    @property
    def name(self) -> str:
        return "slack_post"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return SlackPostInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return SlackPostOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.WRITE

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, SlackPostInput)

        if not self._bot_token:
            return SlackPostOutput(error="Slack bot token not configured")

        params: dict = {
            "channel": input_data.channel,
            "text": input_data.text,
        }
        if input_data.thread_ts:
            params["thread_ts"] = input_data.thread_ts

        result = _slack_api(self._bot_token, "chat.postMessage", params)

        if not result.get("ok"):
            return SlackPostOutput(error=result.get("error", "Unknown error"))

        return SlackPostOutput(
            ok=True,
            ts=result.get("ts", ""),
            channel=result.get("channel", ""),
        )


class SlackReadTool(BaseTool):
    """Read messages from a Slack channel."""

    def __init__(self, *, bot_token: str = "") -> None:
        self._bot_token = bot_token

    @property
    def name(self) -> str:
        return "slack_read"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return SlackReadInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return SlackReadOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.READ

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, SlackReadInput)

        if not self._bot_token:
            return SlackReadOutput(error="Slack bot token not configured")

        params: dict = {
            "channel": input_data.channel,
            "limit": input_data.limit,
        }
        if input_data.oldest:
            params["oldest"] = input_data.oldest

        result = _slack_api(self._bot_token, "conversations.history", params)

        if not result.get("ok"):
            return SlackReadOutput(error=result.get("error", "Unknown error"))

        messages = [
            SlackMessage(
                user=m.get("user", ""),
                text=m.get("text", ""),
                ts=m.get("ts", ""),
                thread_ts=m.get("thread_ts", ""),
            )
            for m in result.get("messages", [])
        ]

        return SlackReadOutput(
            messages=messages,
            has_more=result.get("has_more", False),
        )
