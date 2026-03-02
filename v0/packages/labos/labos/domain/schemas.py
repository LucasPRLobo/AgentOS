"""Pydantic v2 domain schemas for ML replication workflows."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ── Core domain models ──────────────────────────────────────────────


class ExperimentConfig(BaseModel):
    """Configuration for an ML replication experiment."""

    dataset_name: str = "iris"
    model_type: str = "LogisticRegression"
    model_params: dict[str, Any] = Field(default_factory=dict)
    random_seed: int = 42
    test_size: float = Field(default=0.2, gt=0.0, lt=1.0)
    metric_name: str = "accuracy"


class DatasetRecord(BaseModel):
    """Metadata about a loaded dataset."""

    name: str
    n_samples: int = Field(ge=0)
    n_features: int = Field(ge=0)
    n_classes: int = Field(ge=0)
    feature_names: list[str] = Field(default_factory=list)
    target_names: list[str] = Field(default_factory=list)
    checksum: str


class TrainingResult(BaseModel):
    """Result of training and evaluating a model."""

    model_type: str
    model_params: dict[str, Any] = Field(default_factory=dict)
    metric_name: str
    metric_value: float
    train_samples: int = Field(ge=0)
    test_samples: int = Field(ge=0)
    seed: int
    duration_seconds: float = Field(ge=0.0)


class PlotRecord(BaseModel):
    """Metadata about a generated plot."""

    path: str
    sha256: str
    title: str
    plot_type: str = "confusion_matrix"


class ReportRecord(BaseModel):
    """Metadata about a generated report."""

    path: str
    sha256: str
    title: str
    sections: list[str] = Field(default_factory=list)


class EnvironmentSpec(BaseModel):
    """Captures the runtime environment for reproducibility."""

    python_version: str
    platform: str
    sklearn_version: str = ""
    matplotlib_version: str = ""
    timestamp: str = ""


class ReproducibilityRecord(BaseModel):
    """Full reproducibility record for an experiment run."""

    seed: int
    dataset_checksum: str
    config_hash: str
    environment_spec: EnvironmentSpec
    code_version: str = ""
    dataset_record: DatasetRecord | None = None
    training_result: TrainingResult | None = None
    plot_record: PlotRecord | None = None
    report_record: ReportRecord | None = None


class ReviewResult(BaseModel):
    """Result of a reproducibility review."""

    passed: bool
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary: str = ""


# ── Tool I/O schemas ────────────────────────────────────────────────


class DatasetInput(BaseModel):
    """Input for DatasetTool."""

    config: ExperimentConfig


class DatasetOutput(BaseModel):
    """Output from DatasetTool."""

    record: DatasetRecord


class PythonRunnerInput(BaseModel):
    """Input for PythonRunnerTool."""

    config: ExperimentConfig
    dataset_record: DatasetRecord


class PythonRunnerOutput(BaseModel):
    """Output from PythonRunnerTool."""

    result: TrainingResult


class PlotInput(BaseModel):
    """Input for PlotTool."""

    config: ExperimentConfig
    dataset_record: DatasetRecord
    training_result: TrainingResult
    output_dir: str = "."


class PlotOutput(BaseModel):
    """Output from PlotTool."""

    record: PlotRecord


class ReportInput(BaseModel):
    """Input for ReportTool."""

    config: ExperimentConfig
    dataset_record: DatasetRecord
    training_result: TrainingResult
    plot_record: PlotRecord | None = None
    output_dir: str = "."


class ReportOutput(BaseModel):
    """Output from ReportTool."""

    record: ReportRecord


class ReviewerInput(BaseModel):
    """Input for ReviewerTool."""

    reproducibility_record: ReproducibilityRecord


class ReviewerOutput(BaseModel):
    """Output from ReviewerTool."""

    result: ReviewResult
