"""Tests for Google Workspace integration tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agentplatform.tools.google.auth import GoogleCredentials
from agentplatform.tools.google.gmail import (
    GmailReadOutput,
    GmailReadTool,
    GmailSendOutput,
    GmailSendTool,
    GmailReadInput,
    GmailSendInput,
)
from agentplatform.tools.google.sheets import (
    GoogleSheetsReadTool,
    GoogleSheetsWriteTool,
    SheetsReadInput,
    SheetsReadOutput,
    SheetsWriteInput,
    SheetsWriteOutput,
)
from agentplatform.tools.google.docs import (
    GoogleDocsReadTool,
    GoogleDocsWriteTool,
    DocsReadInput,
    DocsReadOutput,
    DocsWriteInput,
    DocsWriteOutput,
)
from agentplatform.tools.google.drive import (
    GoogleDriveListTool,
    GoogleDriveDownloadTool,
    DriveListInput,
    DriveListOutput,
    DriveDownloadInput,
    DriveDownloadOutput,
)


@pytest.fixture()
def creds() -> GoogleCredentials:
    return GoogleCredentials(access_token="test-token")


class TestGoogleCredentials:
    def test_valid_when_token_present(self) -> None:
        creds = GoogleCredentials(access_token="tok")
        assert creds.valid is True

    def test_invalid_when_empty(self) -> None:
        creds = GoogleCredentials()
        assert creds.valid is False


class TestGmailTools:
    def test_read_tool_name(self, creds: GoogleCredentials) -> None:
        tool = GmailReadTool(credentials=creds)
        assert tool.name == "gmail_read"

    def test_send_tool_name(self, creds: GoogleCredentials) -> None:
        tool = GmailSendTool(credentials=creds)
        assert tool.name == "gmail_send"

    def test_read_missing_dependency(self, creds: GoogleCredentials) -> None:
        tool = GmailReadTool(credentials=creds)
        with patch("agentplatform.tools.google.gmail.build_google_service") as mock_build:
            mock_build.side_effect = ImportError("google-api not installed")
            result = tool.execute(GmailReadInput(query="test"))
            assert isinstance(result, GmailReadOutput)
            assert result.error is not None
            assert "not installed" in result.error

    def test_send_missing_dependency(self, creds: GoogleCredentials) -> None:
        tool = GmailSendTool(credentials=creds)
        with patch("agentplatform.tools.google.gmail.build_google_service") as mock_build:
            mock_build.side_effect = ImportError("google-api not installed")
            result = tool.execute(GmailSendInput(to="a@b.com", subject="Hi", body="test"))
            assert isinstance(result, GmailSendOutput)
            assert result.error is not None


class TestSheetsTools:
    def test_read_tool_name(self, creds: GoogleCredentials) -> None:
        tool = GoogleSheetsReadTool(credentials=creds)
        assert tool.name == "google_sheets_read"

    def test_write_tool_name(self, creds: GoogleCredentials) -> None:
        tool = GoogleSheetsWriteTool(credentials=creds)
        assert tool.name == "google_sheets_write"

    def test_read_with_mock_service(self, creds: GoogleCredentials) -> None:
        tool = GoogleSheetsReadTool(credentials=creds)
        mock_service = MagicMock()
        mock_service.spreadsheets().values().get().execute.return_value = {
            "values": [["A", "B"], ["1", "2"]],
        }
        with patch("agentplatform.tools.google.sheets.build_google_service", return_value=mock_service):
            result = tool.execute(SheetsReadInput(spreadsheet_id="id123"))
            assert isinstance(result, SheetsReadOutput)
            assert result.rows == 2
            assert result.cols == 2
            assert result.error is None

    def test_write_with_mock_service(self, creds: GoogleCredentials) -> None:
        tool = GoogleSheetsWriteTool(credentials=creds)
        mock_service = MagicMock()
        mock_service.spreadsheets().values().update().execute.return_value = {
            "updatedCells": 4,
            "updatedRange": "Sheet1!A1:B2",
        }
        with patch("agentplatform.tools.google.sheets.build_google_service", return_value=mock_service):
            result = tool.execute(SheetsWriteInput(
                spreadsheet_id="id123",
                values=[["A", "B"], ["1", "2"]],
            ))
            assert isinstance(result, SheetsWriteOutput)
            assert result.updated_cells == 4


class TestDocsTools:
    def test_read_tool_name(self, creds: GoogleCredentials) -> None:
        tool = GoogleDocsReadTool(credentials=creds)
        assert tool.name == "google_docs_read"

    def test_write_tool_name(self, creds: GoogleCredentials) -> None:
        tool = GoogleDocsWriteTool(credentials=creds)
        assert tool.name == "google_docs_write"

    def test_read_extracts_text(self, creds: GoogleCredentials) -> None:
        tool = GoogleDocsReadTool(credentials=creds)
        mock_service = MagicMock()
        mock_service.documents().get().execute.return_value = {
            "title": "Test Doc",
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [
                                {"textRun": {"content": "Hello world\n"}},
                            ]
                        }
                    }
                ]
            },
        }
        with patch("agentplatform.tools.google.docs.build_google_service", return_value=mock_service):
            result = tool.execute(DocsReadInput(document_id="doc123"))
            assert isinstance(result, DocsReadOutput)
            assert result.title == "Test Doc"
            assert "Hello world" in result.body_text


class TestDriveTools:
    def test_list_tool_name(self, creds: GoogleCredentials) -> None:
        tool = GoogleDriveListTool(credentials=creds)
        assert tool.name == "google_drive_list"

    def test_download_tool_name(self, creds: GoogleCredentials) -> None:
        tool = GoogleDriveDownloadTool(credentials=creds)
        assert tool.name == "google_drive_download"

    def test_list_with_mock_service(self, creds: GoogleCredentials) -> None:
        tool = GoogleDriveListTool(credentials=creds)
        mock_service = MagicMock()
        mock_service.files().list().execute.return_value = {
            "files": [
                {"id": "f1", "name": "report.pdf", "mimeType": "application/pdf",
                 "size": "1024", "modifiedTime": "2024-01-01"},
            ]
        }
        with patch("agentplatform.tools.google.drive.build_google_service", return_value=mock_service):
            result = tool.execute(DriveListInput())
            assert isinstance(result, DriveListOutput)
            assert len(result.files) == 1
            assert result.files[0].name == "report.pdf"

    def test_download_path_traversal_blocked(self, creds: GoogleCredentials, tmp_path) -> None:
        tool = GoogleDriveDownloadTool(credentials=creds, workspace_dir=tmp_path)
        result = tool.execute(DriveDownloadInput(
            file_id="f1", save_path="../../etc/passwd"
        ))
        assert isinstance(result, DriveDownloadOutput)
        assert result.error is not None
        assert "outside workspace" in result.error
