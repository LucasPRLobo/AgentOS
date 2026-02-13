"""Evaluation cases for ML replication workflows."""

from __future__ import annotations

import tempfile
import time

from agentos.eval.eval_case import EvalCase, EvalOutcome, EvalResult
from agentos.runtime.event_log import SQLiteEventLog

from labos.domain.schemas import (
    DatasetInput,
    DatasetRecord,
    EnvironmentSpec,
    ExperimentConfig,
    PythonRunnerInput,
    ReproducibilityRecord,
    ReviewerInput,
    TrainingResult,
)
from labos.tools.dataset import DatasetTool
from labos.tools.python_runner import PythonRunnerTool
from labos.tools.reviewer import ReviewerTool
from labos.workflows.ml_replication import run_dag_pipeline


class DatasetDeterminismEval(EvalCase):
    """Load iris dataset twice — checksums must match."""

    @property
    def name(self) -> str:
        return "dataset_determinism"

    @property
    def tags(self) -> list[str]:
        return ["determinism", "dataset"]

    def run(self) -> EvalResult:
        start = time.monotonic()
        try:
            config = ExperimentConfig(dataset_name="iris", random_seed=42)
            tool = DatasetTool()

            out1 = tool.execute(DatasetInput(config=config))
            out2 = tool.execute(DatasetInput(config=config))

            match = out1.record.checksum == out2.record.checksum
            duration = time.monotonic() - start

            return EvalResult(
                case_name=self.name,
                outcome=EvalOutcome.PASSED if match else EvalOutcome.FAILED,
                duration_seconds=duration,
                metrics={"checksums_match": 1.0 if match else 0.0},
                error_message=None if match else "Checksums differ between identical loads",
            )
        except Exception as exc:
            return EvalResult(
                case_name=self.name,
                outcome=EvalOutcome.ERROR,
                duration_seconds=time.monotonic() - start,
                error_message=str(exc),
                error_type=type(exc).__name__,
            )
        finally:
            DatasetTool.clear_cache()


class TrainingDeterminismEval(EvalCase):
    """Train twice with same seed — metrics must match exactly."""

    @property
    def name(self) -> str:
        return "training_determinism"

    @property
    def tags(self) -> list[str]:
        return ["determinism", "training"]

    def run(self) -> EvalResult:
        start = time.monotonic()
        try:
            config = ExperimentConfig(dataset_name="iris", random_seed=42)
            dataset_tool = DatasetTool()
            runner_tool = PythonRunnerTool()

            ds_out = dataset_tool.execute(DatasetInput(config=config))

            out1 = runner_tool.execute(
                PythonRunnerInput(config=config, dataset_record=ds_out.record)
            )
            out2 = runner_tool.execute(
                PythonRunnerInput(config=config, dataset_record=ds_out.record)
            )

            match = out1.result.metric_value == out2.result.metric_value
            duration = time.monotonic() - start

            return EvalResult(
                case_name=self.name,
                outcome=EvalOutcome.PASSED if match else EvalOutcome.FAILED,
                duration_seconds=duration,
                metrics={
                    "run1_accuracy": out1.result.metric_value,
                    "run2_accuracy": out2.result.metric_value,
                    "metrics_match": 1.0 if match else 0.0,
                },
                error_message=None if match else "Metrics differ between identical training runs",
            )
        except Exception as exc:
            return EvalResult(
                case_name=self.name,
                outcome=EvalOutcome.ERROR,
                duration_seconds=time.monotonic() - start,
                error_message=str(exc),
                error_type=type(exc).__name__,
            )
        finally:
            DatasetTool.clear_cache()


class DAGPipelineEval(EvalCase):
    """Full DAG pipeline run must succeed."""

    @property
    def name(self) -> str:
        return "dag_pipeline"

    @property
    def tags(self) -> list[str]:
        return ["pipeline", "dag"]

    def run(self) -> EvalResult:
        start = time.monotonic()
        try:
            config = ExperimentConfig(dataset_name="iris", random_seed=42)
            event_log = SQLiteEventLog()

            with tempfile.TemporaryDirectory() as tmpdir:
                rid = run_dag_pipeline(config, event_log=event_log, output_dir=tmpdir)

            events = event_log.replay(rid)
            last = events[-1]
            outcome_str = last.payload.get("outcome", "UNKNOWN")
            succeeded = outcome_str == "SUCCEEDED"
            duration = time.monotonic() - start

            return EvalResult(
                case_name=self.name,
                outcome=EvalOutcome.PASSED if succeeded else EvalOutcome.FAILED,
                duration_seconds=duration,
                metrics={"total_events": float(len(events))},
                error_message=None if succeeded else f"DAG outcome: {outcome_str}",
            )
        except Exception as exc:
            return EvalResult(
                case_name=self.name,
                outcome=EvalOutcome.ERROR,
                duration_seconds=time.monotonic() - start,
                error_message=str(exc),
                error_type=type(exc).__name__,
            )
        finally:
            DatasetTool.clear_cache()


class ReviewerValidationEval(EvalCase):
    """Reviewer passes valid record and rejects empty checksum."""

    @property
    def name(self) -> str:
        return "reviewer_validation"

    @property
    def tags(self) -> list[str]:
        return ["reviewer", "validation"]

    def run(self) -> EvalResult:
        start = time.monotonic()
        try:
            reviewer = ReviewerTool()

            # Valid record
            valid_rec = ReproducibilityRecord(
                seed=42,
                dataset_checksum="abc123",
                config_hash="def456",
                environment_spec=EnvironmentSpec(
                    python_version="3.11.0",
                    platform="linux",
                    sklearn_version="1.3.0",
                ),
                dataset_record=DatasetRecord(
                    name="iris", n_samples=150, n_features=4,
                    n_classes=3, checksum="abc123",
                ),
                training_result=TrainingResult(
                    model_type="LogisticRegression",
                    metric_name="accuracy", metric_value=0.97,
                    train_samples=120, test_samples=30,
                    seed=42, duration_seconds=0.01,
                ),
            )
            valid_out = reviewer.execute(ReviewerInput(reproducibility_record=valid_rec))
            valid_passed = valid_out.result.passed

            # Invalid: empty checksum
            invalid_rec = valid_rec.model_copy(update={"dataset_checksum": ""})
            invalid_out = reviewer.execute(ReviewerInput(reproducibility_record=invalid_rec))
            invalid_rejected = not invalid_out.result.passed

            both_ok = valid_passed and invalid_rejected
            duration = time.monotonic() - start

            return EvalResult(
                case_name=self.name,
                outcome=EvalOutcome.PASSED if both_ok else EvalOutcome.FAILED,
                duration_seconds=duration,
                metrics={
                    "valid_passes": 1.0 if valid_passed else 0.0,
                    "invalid_rejected": 1.0 if invalid_rejected else 0.0,
                },
                error_message=None if both_ok else "Reviewer validation logic incorrect",
            )
        except Exception as exc:
            return EvalResult(
                case_name=self.name,
                outcome=EvalOutcome.ERROR,
                duration_seconds=time.monotonic() - start,
                error_message=str(exc),
                error_type=type(exc).__name__,
            )
