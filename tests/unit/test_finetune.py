"""Tests for fine-tuning data pipeline."""

from __future__ import annotations

import json

import pytest

from agentos.intelligence.finetune import (
    ExportConfig,
    ExportFormat,
    FineTuneExporter,
    TaskRecord,
)


def _make_record(
    quality: float = 0.9,
    approved: bool = True,
    task_id: str = "",
) -> TaskRecord:
    return TaskRecord(
        task_id=task_id or f"t-{id(quality)}",
        workflow_id="wf-1",
        system_prompt="You are a helpful assistant.",
        user_input="Analyze this data",
        assistant_output="Here is my analysis...",
        quality_score=quality,
        approved=approved,
    )


@pytest.fixture
def exporter() -> FineTuneExporter:
    return FineTuneExporter()


class TestExport:
    def test_export_approved_records(self, exporter):
        for i in range(5):
            exporter.add_record(_make_record(quality=0.9, task_id=f"t-{i}"))
        result = exporter.export()
        assert result.exported == 5
        assert result.total_candidates == 5

    def test_filter_low_quality(self, exporter):
        exporter.add_record(_make_record(quality=0.5, task_id="low"))
        exporter.add_record(_make_record(quality=0.9, task_id="high"))
        result = exporter.export()
        assert result.exported == 1
        assert result.filtered_quality == 1

    def test_filter_unapproved(self, exporter):
        exporter.add_record(_make_record(approved=False, task_id="rejected"))
        exporter.add_record(_make_record(approved=True, task_id="approved"))
        result = exporter.export()
        assert result.exported == 1
        assert result.filtered_approval == 1

    def test_max_examples_limit(self, exporter):
        for i in range(20):
            exporter.add_record(_make_record(task_id=f"t-{i}"))
        config = ExportConfig(max_examples=5)
        result = exporter.export(config)
        assert result.exported == 5

    def test_custom_quality_threshold(self, exporter):
        exporter.add_record(_make_record(quality=0.6, task_id="t1"))
        exporter.add_record(_make_record(quality=0.9, task_id="t2"))
        config = ExportConfig(min_quality_score=0.5)
        result = exporter.export(config)
        assert result.exported == 2


class TestFormats:
    def test_openai_format(self, exporter):
        exporter.add_record(_make_record(task_id="t1"))
        config = ExportConfig(format=ExportFormat.JSONL_OPENAI)
        result = exporter.export(config)
        data = json.loads(result.lines[0])
        assert "messages" in data
        assert len(data["messages"]) == 3
        assert data["messages"][0]["role"] == "system"
        assert data["messages"][1]["role"] == "user"
        assert data["messages"][2]["role"] == "assistant"

    def test_anthropic_format(self, exporter):
        exporter.add_record(_make_record(task_id="t1"))
        config = ExportConfig(format=ExportFormat.JSONL_ANTHROPIC)
        result = exporter.export(config)
        data = json.loads(result.lines[0])
        assert "system" in data
        assert "messages" in data
        assert len(data["messages"]) == 2

    def test_jsonl_string(self, exporter):
        for i in range(3):
            exporter.add_record(_make_record(task_id=f"t-{i}"))
        jsonl = exporter.export_jsonl()
        lines = jsonl.strip().split("\n")
        assert len(lines) == 3
        for line in lines:
            json.loads(line)  # Each line is valid JSON

    def test_each_line_valid_json(self, exporter):
        exporter.add_record(_make_record(task_id="t1"))
        result = exporter.export()
        for line in result.lines:
            data = json.loads(line)
            assert isinstance(data, dict)


class TestMultiProviderOutput:
    def test_same_data_different_formats(self, exporter):
        exporter.add_record(_make_record(task_id="t1"))

        openai_result = exporter.export(ExportConfig(format=ExportFormat.JSONL_OPENAI))
        anthropic_result = exporter.export(ExportConfig(format=ExportFormat.JSONL_ANTHROPIC))

        openai_data = json.loads(openai_result.lines[0])
        anthropic_data = json.loads(anthropic_result.lines[0])

        # Both contain the same content
        assert openai_data["messages"][2]["content"] == anthropic_data["messages"][1]["content"]
        # But in different structures
        assert "system" not in openai_data  # OpenAI puts system in messages
        assert "system" in anthropic_data


class TestRecordCount:
    def test_record_count(self, exporter):
        assert exporter.record_count == 0
        exporter.add_record(_make_record(task_id="t1"))
        assert exporter.record_count == 1
