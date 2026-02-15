"""Gmail tools — read and send emails."""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from typing import Any

from pydantic import BaseModel, Field

from agentos.tools.base import BaseTool, SideEffect

from .auth import GoogleCredentials, build_google_service


# ── Schemas ────────────────────────────────────────────────────────


class GmailReadInput(BaseModel):
    query: str = Field(default="is:unread", description="Gmail search query")
    max_results: int = Field(default=10, ge=1, le=50)


class EmailMessage(BaseModel):
    id: str = ""
    subject: str = ""
    sender: str = ""
    snippet: str = ""
    date: str = ""


class GmailReadOutput(BaseModel):
    messages: list[EmailMessage] = Field(default_factory=list)
    total: int = 0
    error: str | None = None


class GmailSendInput(BaseModel):
    to: str = Field(..., description="Recipient email address")
    subject: str = Field(default="", description="Email subject")
    body: str = Field(default="", description="Email body (plain text)")


class GmailSendOutput(BaseModel):
    message_id: str = ""
    thread_id: str = ""
    error: str | None = None


# ── Tools ──────────────────────────────────────────────────────────


class GmailReadTool(BaseTool):
    """Read emails from Gmail."""

    def __init__(self, *, credentials: GoogleCredentials) -> None:
        self._credentials = credentials

    @property
    def name(self) -> str:
        return "gmail_read"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return GmailReadInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return GmailReadOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.READ

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, GmailReadInput)

        try:
            service = build_google_service(self._credentials, "gmail", "v1")
        except ImportError as exc:
            return GmailReadOutput(error=str(exc))

        try:
            result = service.users().messages().list(
                userId="me", q=input_data.query, maxResults=input_data.max_results,
            ).execute()
        except Exception as exc:
            return GmailReadOutput(error=f"Gmail API error: {exc}")

        messages: list[EmailMessage] = []
        for msg_ref in result.get("messages", []):
            try:
                msg = service.users().messages().get(
                    userId="me", id=msg_ref["id"], format="metadata",
                    metadataHeaders=["Subject", "From", "Date"],
                ).execute()
                headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                messages.append(EmailMessage(
                    id=msg["id"],
                    subject=headers.get("Subject", ""),
                    sender=headers.get("From", ""),
                    snippet=msg.get("snippet", ""),
                    date=headers.get("Date", ""),
                ))
            except Exception:
                continue

        return GmailReadOutput(messages=messages, total=len(messages))


class GmailSendTool(BaseTool):
    """Send an email via Gmail."""

    def __init__(self, *, credentials: GoogleCredentials) -> None:
        self._credentials = credentials

    @property
    def name(self) -> str:
        return "gmail_send"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return GmailSendInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return GmailSendOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.WRITE

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, GmailSendInput)

        try:
            service = build_google_service(self._credentials, "gmail", "v1")
        except ImportError as exc:
            return GmailSendOutput(error=str(exc))

        mime = MIMEText(input_data.body)
        mime["to"] = input_data.to
        mime["subject"] = input_data.subject
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")

        try:
            sent = service.users().messages().send(
                userId="me", body={"raw": raw},
            ).execute()
            return GmailSendOutput(
                message_id=sent.get("id", ""),
                thread_id=sent.get("threadId", ""),
            )
        except Exception as exc:
            return GmailSendOutput(error=f"Gmail send failed: {exc}")
