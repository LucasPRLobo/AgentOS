"""ReportTool — generates markdown experiment reports."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from agentos.integrity.hashing import hash_file
from agentos.tools.base import BaseTool, SideEffect

from labos.domain.schemas import ReportInput, ReportOutput, ReportRecord


class ReportTool(BaseTool):
    """Generate a markdown report summarising the experiment."""

    @property
    def name(self) -> str:
        return "report_generator"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return ReportInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return ReportOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.WRITE

    def execute(self, input_data: BaseModel) -> BaseModel:
        data = input_data if isinstance(input_data, ReportInput) else ReportInput.model_validate(input_data.model_dump())
        config = data.config
        ds = data.dataset_record
        tr = data.training_result
        plot = data.plot_record
        output_dir = Path(data.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        sections = ["Summary", "Dataset", "Model Configuration", "Results", "Reproducibility"]

        lines: list[str] = []
        title = f"ML Replication Report — {config.model_type} on {ds.name}"
        lines.append(f"# {title}\n")

        # Summary
        lines.append("## Summary\n")
        lines.append(f"Replicated **{config.model_type}** on the **{ds.name}** dataset.")
        lines.append(f"Achieved **{tr.metric_value:.4f}** {tr.metric_name}.\n")

        # Dataset
        lines.append("## Dataset\n")
        lines.append(f"- **Name**: {ds.name}")
        lines.append(f"- **Samples**: {ds.n_samples}")
        lines.append(f"- **Features**: {ds.n_features}")
        lines.append(f"- **Classes**: {ds.n_classes}")
        lines.append(f"- **Checksum**: `{ds.checksum[:16]}...`\n")

        # Model Configuration
        lines.append("## Model Configuration\n")
        lines.append(f"- **Type**: {config.model_type}")
        lines.append(f"- **Random seed**: {config.random_seed}")
        lines.append(f"- **Test size**: {config.test_size}")
        if tr.model_params:
            lines.append("- **Parameters**:")
            for k, v in sorted(tr.model_params.items()):
                lines.append(f"  - `{k}`: {v}")
        lines.append("")

        # Results
        lines.append("## Results\n")
        lines.append(f"- **{tr.metric_name}**: {tr.metric_value:.4f}")
        lines.append(f"- **Train samples**: {tr.train_samples}")
        lines.append(f"- **Test samples**: {tr.test_samples}")
        lines.append(f"- **Training duration**: {tr.duration_seconds:.4f}s\n")

        # Reproducibility
        lines.append("## Reproducibility\n")
        lines.append(f"- **Seed**: {config.random_seed}")
        lines.append(f"- **Dataset checksum**: `{ds.checksum[:16]}...`\n")

        # Visualizations (optional)
        if plot:
            sections.append("Visualizations")
            lines.append("## Visualizations\n")
            lines.append(f"![{plot.title}]({plot.path})\n")
            lines.append(f"- **Plot hash**: `{plot.sha256[:16]}...`\n")

        report_path = output_dir / "report.md"
        content = "\n".join(lines)
        report_path.write_text(content)

        sha = hash_file(report_path)

        record = ReportRecord(
            path=str(report_path),
            sha256=sha,
            title=title,
            sections=sections,
        )
        return ReportOutput(record=record)
