"""Google Docs tools — read and write documents."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agentos.tools.base import BaseTool, SideEffect

from .auth import GoogleCredentials, build_google_service


# ── Schemas ────────────────────────────────────────────────────────


class DocsReadInput(BaseModel):
    document_id: str = Field(..., description="Google Docs document ID")


class DocsReadOutput(BaseModel):
    title: str = ""
    body_text: str = ""
    error: str | None = None


class DocsWriteInput(BaseModel):
    document_id: str = Field(..., description="Google Docs document ID")
    text: str = Field(..., description="Text to append to the document")


class DocsWriteOutput(BaseModel):
    success: bool = False
    error: str | None = None


# ── Helpers ────────────────────────────────────────────────────────


def _extract_text(doc: dict) -> str:
    """Extract plain text from a Google Docs document body."""
    parts: list[str] = []
    body = doc.get("body", {})
    for element in body.get("content", []):
        paragraph = element.get("paragraph")
        if paragraph:
            for elem in paragraph.get("elements", []):
                text_run = elem.get("textRun")
                if text_run:
                    parts.append(text_run.get("content", ""))
    return "".join(parts)


# ── Tools ──────────────────────────────────────────────────────────


class GoogleDocsReadTool(BaseTool):
    """Read the contents of a Google Docs document."""

    def __init__(self, *, credentials: GoogleCredentials) -> None:
        self._credentials = credentials

    @property
    def name(self) -> str:
        return "google_docs_read"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return DocsReadInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return DocsReadOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.READ

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, DocsReadInput)

        try:
            service = build_google_service(self._credentials, "docs", "v1")
        except ImportError as exc:
            return DocsReadOutput(error=str(exc))

        try:
            doc = service.documents().get(documentId=input_data.document_id).execute()
            return DocsReadOutput(
                title=doc.get("title", ""),
                body_text=_extract_text(doc),
            )
        except Exception as exc:
            return DocsReadOutput(error=f"Docs API error: {exc}")


class GoogleDocsWriteTool(BaseTool):
    """Append text to a Google Docs document."""

    def __init__(self, *, credentials: GoogleCredentials) -> None:
        self._credentials = credentials

    @property
    def name(self) -> str:
        return "google_docs_write"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return DocsWriteInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return DocsWriteOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.WRITE

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, DocsWriteInput)

        try:
            service = build_google_service(self._credentials, "docs", "v1")
        except ImportError as exc:
            return DocsWriteOutput(error=str(exc))

        try:
            # Get document to find end index
            doc = service.documents().get(documentId=input_data.document_id).execute()
            body = doc.get("body", {})
            content = body.get("content", [])
            end_index = content[-1]["endIndex"] - 1 if content else 1

            # Insert text at end
            service.documents().batchUpdate(
                documentId=input_data.document_id,
                body={
                    "requests": [{
                        "insertText": {
                            "location": {"index": end_index},
                            "text": input_data.text,
                        }
                    }]
                },
            ).execute()
            return DocsWriteOutput(success=True)
        except Exception as exc:
            return DocsWriteOutput(error=f"Docs write failed: {exc}")
