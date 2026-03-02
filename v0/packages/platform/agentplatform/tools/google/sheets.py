"""Google Sheets tools — read and write spreadsheet data."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agentos.tools.base import BaseTool, SideEffect

from .auth import GoogleCredentials, build_google_service


# ── Schemas ────────────────────────────────────────────────────────


class SheetsReadInput(BaseModel):
    spreadsheet_id: str = Field(..., description="Google Sheets spreadsheet ID")
    range: str = Field(default="Sheet1", description="A1 notation range (e.g. 'Sheet1!A1:D10')")


class SheetsReadOutput(BaseModel):
    values: list[list[str]] = Field(default_factory=list)
    rows: int = 0
    cols: int = 0
    error: str | None = None


class SheetsWriteInput(BaseModel):
    spreadsheet_id: str = Field(..., description="Google Sheets spreadsheet ID")
    range: str = Field(default="Sheet1!A1", description="A1 notation range to write to")
    values: list[list[str]] = Field(..., description="2D array of values to write")


class SheetsWriteOutput(BaseModel):
    updated_cells: int = 0
    updated_range: str = ""
    error: str | None = None


# ── Tools ──────────────────────────────────────────────────────────


class GoogleSheetsReadTool(BaseTool):
    """Read data from a Google Sheets spreadsheet."""

    def __init__(self, *, credentials: GoogleCredentials) -> None:
        self._credentials = credentials

    @property
    def name(self) -> str:
        return "google_sheets_read"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return SheetsReadInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return SheetsReadOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.READ

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, SheetsReadInput)

        try:
            service = build_google_service(self._credentials, "sheets", "v4")
        except ImportError as exc:
            return SheetsReadOutput(error=str(exc))

        try:
            result = service.spreadsheets().values().get(
                spreadsheetId=input_data.spreadsheet_id,
                range=input_data.range,
            ).execute()
            values = result.get("values", [])
            rows = len(values)
            cols = max((len(r) for r in values), default=0)
            return SheetsReadOutput(values=values, rows=rows, cols=cols)
        except Exception as exc:
            return SheetsReadOutput(error=f"Sheets API error: {exc}")


class GoogleSheetsWriteTool(BaseTool):
    """Write data to a Google Sheets spreadsheet."""

    def __init__(self, *, credentials: GoogleCredentials) -> None:
        self._credentials = credentials

    @property
    def name(self) -> str:
        return "google_sheets_write"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return SheetsWriteInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return SheetsWriteOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.WRITE

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, SheetsWriteInput)

        try:
            service = build_google_service(self._credentials, "sheets", "v4")
        except ImportError as exc:
            return SheetsWriteOutput(error=str(exc))

        try:
            result = service.spreadsheets().values().update(
                spreadsheetId=input_data.spreadsheet_id,
                range=input_data.range,
                valueInputOption="USER_ENTERED",
                body={"values": input_data.values},
            ).execute()
            return SheetsWriteOutput(
                updated_cells=result.get("updatedCells", 0),
                updated_range=result.get("updatedRange", ""),
            )
        except Exception as exc:
            return SheetsWriteOutput(error=f"Sheets write failed: {exc}")
