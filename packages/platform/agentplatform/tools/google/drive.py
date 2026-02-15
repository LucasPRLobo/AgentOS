"""Google Drive tools — list and download files."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from agentos.tools.base import BaseTool, SideEffect

from .auth import GoogleCredentials, build_google_service


# ── Schemas ────────────────────────────────────────────────────────


class DriveListInput(BaseModel):
    query: str = Field(
        default="", description="Drive search query (e.g. \"name contains 'report'\")"
    )
    max_results: int = Field(default=20, ge=1, le=100)
    folder_id: str = Field(default="", description="Restrict to a specific folder ID")


class DriveFile(BaseModel):
    id: str = ""
    name: str = ""
    mime_type: str = ""
    size: str = ""
    modified_time: str = ""


class DriveListOutput(BaseModel):
    files: list[DriveFile] = Field(default_factory=list)
    total: int = 0
    error: str | None = None


class DriveDownloadInput(BaseModel):
    file_id: str = Field(..., description="Google Drive file ID to download")
    save_path: str = Field(..., description="Local path to save the file (relative to workspace)")


class DriveDownloadOutput(BaseModel):
    saved_path: str = ""
    size_bytes: int = 0
    error: str | None = None


# ── Tools ──────────────────────────────────────────────────────────


class GoogleDriveListTool(BaseTool):
    """List files in Google Drive."""

    def __init__(self, *, credentials: GoogleCredentials) -> None:
        self._credentials = credentials

    @property
    def name(self) -> str:
        return "google_drive_list"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return DriveListInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return DriveListOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.READ

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, DriveListInput)

        try:
            service = build_google_service(self._credentials, "drive", "v3")
        except ImportError as exc:
            return DriveListOutput(error=str(exc))

        q_parts: list[str] = []
        if input_data.query:
            q_parts.append(input_data.query)
        if input_data.folder_id:
            q_parts.append(f"'{input_data.folder_id}' in parents")

        try:
            result = service.files().list(
                q=" and ".join(q_parts) if q_parts else None,
                pageSize=input_data.max_results,
                fields="files(id, name, mimeType, size, modifiedTime)",
            ).execute()

            files = [
                DriveFile(
                    id=f.get("id", ""),
                    name=f.get("name", ""),
                    mime_type=f.get("mimeType", ""),
                    size=f.get("size", ""),
                    modified_time=f.get("modifiedTime", ""),
                )
                for f in result.get("files", [])
            ]
            return DriveListOutput(files=files, total=len(files))
        except Exception as exc:
            return DriveListOutput(error=f"Drive API error: {exc}")


class GoogleDriveDownloadTool(BaseTool):
    """Download a file from Google Drive."""

    def __init__(
        self, *, credentials: GoogleCredentials, workspace_dir: str | Path = "."
    ) -> None:
        self._credentials = credentials
        self._workspace_dir = Path(workspace_dir).resolve()

    @property
    def name(self) -> str:
        return "google_drive_download"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return DriveDownloadInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return DriveDownloadOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.READ

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, DriveDownloadInput)

        save_path = (self._workspace_dir / input_data.save_path).resolve()
        try:
            save_path.relative_to(self._workspace_dir)
        except ValueError:
            return DriveDownloadOutput(error="Save path is outside workspace")

        try:
            service = build_google_service(self._credentials, "drive", "v3")
        except ImportError as exc:
            return DriveDownloadOutput(error=str(exc))

        try:
            from io import BytesIO

            from googleapiclient.http import MediaIoBaseDownload

            request = service.files().get_media(fileId=input_data.file_id)
            buffer = BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

            save_path.parent.mkdir(parents=True, exist_ok=True)
            data = buffer.getvalue()
            save_path.write_bytes(data)

            return DriveDownloadOutput(
                saved_path=str(save_path.relative_to(self._workspace_dir)),
                size_bytes=len(data),
            )
        except Exception as exc:
            return DriveDownloadOutput(error=f"Drive download failed: {exc}")
