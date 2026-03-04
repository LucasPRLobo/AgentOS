"""Fine-tuning data pipeline — extract training data from approved outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum


class ExportFormat(StrEnum):
    JSONL_OPENAI = "jsonl_openai"
    JSONL_ANTHROPIC = "jsonl_anthropic"


@dataclass
class TrainingExample:
    """A single training example extracted from a task output."""

    system_prompt: str
    user_message: str
    assistant_response: str
    quality_score: float = 1.0
    source_workflow: str = ""
    source_task: str = ""


@dataclass
class ExportConfig:
    """Configuration for fine-tuning data export."""

    format: ExportFormat = ExportFormat.JSONL_OPENAI
    min_quality_score: float = 0.7
    min_approval_rate: float = 0.8
    max_examples: int = 10000


@dataclass
class ExportResult:
    """Result of a fine-tuning data export."""

    total_candidates: int = 0
    exported: int = 0
    filtered_quality: int = 0
    filtered_approval: int = 0
    lines: list[str] = field(default_factory=list)


@dataclass
class TaskRecord:
    """A record of a completed task for fine-tuning extraction."""

    task_id: str
    workflow_id: str
    system_prompt: str
    user_input: str
    assistant_output: str
    quality_score: float
    approved: bool
    gate_feedback: str = ""


class FineTuneExporter:
    """Exports approved task outputs as fine-tuning training data.

    Applies quality filters (min confidence, min approval rate)
    and outputs in provider-specific JSONL format.
    """

    def __init__(self, config: ExportConfig | None = None) -> None:
        self._config = config or ExportConfig()
        self._records: list[TaskRecord] = []

    def add_record(self, record: TaskRecord) -> None:
        """Add a task record for potential export."""
        self._records.append(record)

    def export(self, config: ExportConfig | None = None) -> ExportResult:
        """Export filtered records as JSONL lines."""
        cfg = config or self._config
        result = ExportResult(total_candidates=len(self._records))

        filtered: list[TaskRecord] = []
        for record in self._records:
            if record.quality_score < cfg.min_quality_score:
                result.filtered_quality += 1
                continue
            if not record.approved:
                result.filtered_approval += 1
                continue
            filtered.append(record)

        # Apply max limit
        filtered = filtered[:cfg.max_examples]

        for record in filtered:
            if cfg.format == ExportFormat.JSONL_OPENAI:
                line = self._format_openai(record)
            else:
                line = self._format_anthropic(record)
            result.lines.append(line)

        result.exported = len(result.lines)
        return result

    def export_jsonl(self, config: ExportConfig | None = None) -> str:
        """Export as a complete JSONL string."""
        result = self.export(config)
        return "\n".join(result.lines)

    @staticmethod
    def _format_openai(record: TaskRecord) -> str:
        """Format as OpenAI fine-tuning JSONL."""
        data = {
            "messages": [
                {"role": "system", "content": record.system_prompt},
                {"role": "user", "content": record.user_input},
                {"role": "assistant", "content": record.assistant_output},
            ]
        }
        return json.dumps(data)

    @staticmethod
    def _format_anthropic(record: TaskRecord) -> str:
        """Format as Anthropic fine-tuning JSONL."""
        data = {
            "system": record.system_prompt,
            "messages": [
                {"role": "user", "content": record.user_input},
                {"role": "assistant", "content": record.assistant_output},
            ],
        }
        return json.dumps(data)

    @property
    def record_count(self) -> int:
        return len(self._records)
