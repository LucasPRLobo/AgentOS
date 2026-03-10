"""Tests for tier2_shared helpers — manifest extraction fallback."""

from __future__ import annotations

from agentos.adapters.tier2_shared import extract_manifest_from_text


class TestExtractManifestFromText:
    """Tests for extract_manifest_from_text fallback parser."""

    def test_empty_input_returns_none(self):
        assert extract_manifest_from_text("") is None
        assert extract_manifest_from_text("   ") is None
        assert extract_manifest_from_text(None) is None  # type: ignore

    def test_markdown_bullets(self):
        text = (
            "Analysis of the market data complete.\n\n"
            "- Revenue increased by 15% year over year\n"
            "- Customer churn decreased to 3.2%\n"
            "- New market segments identified in Asia\n"
        )
        result = extract_manifest_from_text(text)
        assert result is not None
        assert result["extraction_mode"] == "inferred"
        assert "Analysis of the market data complete" in result["summary"]
        assert len(result["findings"]) == 3
        assert result["findings"][0]["confidence"] == "low"

    def test_numbered_list(self):
        text = (
            "Research complete for the quarterly report.\n\n"
            "1. The S&P 500 gained 12% in Q3 driven by tech sector\n"
            "2. Bond yields remained flat across the curve\n"
            "3) Emerging markets showed strong recovery signals\n"
        )
        result = extract_manifest_from_text(text)
        assert result is not None
        assert len(result["findings"]) == 3
        assert "S&P 500" in result["findings"][0]["finding"]

    def test_plain_prose_no_bullets(self):
        text = "I completed the analysis of the dataset successfully."
        result = extract_manifest_from_text(text)
        assert result is not None
        assert result["extraction_mode"] == "inferred"
        assert "analysis" in result["summary"].lower()
        assert result["findings"] == []

    def test_file_references_extracted(self):
        text = (
            "Created the following output files.\n\n"
            "- Generated report at ./output/report.pdf\n"
            "- Saved data to /tmp/results.csv\n"
        )
        result = extract_manifest_from_text(text)
        assert result is not None
        files = result["files_produced"]
        assert any("report.pdf" in f for f in files)

    def test_short_bullets_ignored(self):
        """Bullets with < 10 chars should be filtered out."""
        text = (
            "Summary of findings.\n\n"
            "- yes\n"
            "- no\n"
            "- This is a sufficiently long finding to be included\n"
        )
        result = extract_manifest_from_text(text)
        assert result is not None
        # Only the long finding should be included
        assert len(result["findings"]) == 1

    def test_findings_capped_at_10(self):
        bullets = "\n".join(f"- Finding number {i} with enough text to pass filter" for i in range(15))
        text = f"Summary paragraph.\n\n{bullets}"
        result = extract_manifest_from_text(text)
        assert result is not None
        assert len(result["findings"]) <= 10

    def test_summary_limited_to_3_lines(self):
        text = "Line one of the summary.\nLine two of summary.\nLine three of summary.\nLine four should not be included.\n\nBullet section."
        result = extract_manifest_from_text(text)
        assert result is not None
        # Summary should have at most 3 sentences
        assert "Line four" not in result["summary"]
