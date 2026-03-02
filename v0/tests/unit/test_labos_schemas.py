"""Tests for LabOS domain schemas."""

import pytest
from pydantic import ValidationError

from labos.domain.schemas import (
    DatasetInput,
    DatasetOutput,
    DatasetRecord,
    EnvironmentSpec,
    ExperimentConfig,
    PlotRecord,
    PythonRunnerInput,
    PythonRunnerOutput,
    ReportRecord,
    ReproducibilityRecord,
    ReviewerInput,
    ReviewerOutput,
    ReviewResult,
    TrainingResult,
)


class TestExperimentConfig:
    def test_defaults(self) -> None:
        cfg = ExperimentConfig()
        assert cfg.dataset_name == "iris"
        assert cfg.model_type == "LogisticRegression"
        assert cfg.random_seed == 42
        assert cfg.test_size == 0.2
        assert cfg.metric_name == "accuracy"
        assert cfg.model_params == {}

    def test_custom_values(self) -> None:
        cfg = ExperimentConfig(
            dataset_name="synthetic",
            model_type="LogisticRegression",
            model_params={"C": 0.5},
            random_seed=123,
            test_size=0.3,
            metric_name="f1",
        )
        assert cfg.dataset_name == "synthetic"
        assert cfg.model_params == {"C": 0.5}
        assert cfg.random_seed == 123

    def test_round_trip(self) -> None:
        cfg = ExperimentConfig(random_seed=99)
        data = cfg.model_dump()
        cfg2 = ExperimentConfig.model_validate(data)
        assert cfg == cfg2

    def test_invalid_test_size_zero(self) -> None:
        with pytest.raises(ValidationError):
            ExperimentConfig(test_size=0.0)

    def test_invalid_test_size_one(self) -> None:
        with pytest.raises(ValidationError):
            ExperimentConfig(test_size=1.0)


class TestDatasetRecord:
    def test_valid(self) -> None:
        rec = DatasetRecord(
            name="iris", n_samples=150, n_features=4,
            n_classes=3, checksum="abc123",
        )
        assert rec.name == "iris"
        assert rec.feature_names == []

    def test_round_trip(self) -> None:
        rec = DatasetRecord(
            name="iris", n_samples=150, n_features=4,
            n_classes=3, feature_names=["a", "b", "c", "d"],
            target_names=["x", "y", "z"], checksum="abc",
        )
        data = rec.model_dump()
        rec2 = DatasetRecord.model_validate(data)
        assert rec == rec2

    def test_negative_samples_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DatasetRecord(
                name="bad", n_samples=-1, n_features=4,
                n_classes=3, checksum="x",
            )


class TestTrainingResult:
    def test_valid(self) -> None:
        tr = TrainingResult(
            model_type="LogisticRegression",
            metric_name="accuracy", metric_value=0.95,
            train_samples=120, test_samples=30,
            seed=42, duration_seconds=0.01,
        )
        assert tr.metric_value == 0.95
        assert tr.model_params == {}

    def test_round_trip(self) -> None:
        tr = TrainingResult(
            model_type="LR", model_params={"C": 1.0},
            metric_name="acc", metric_value=0.8,
            train_samples=80, test_samples=20,
            seed=1, duration_seconds=0.5,
        )
        data = tr.model_dump()
        tr2 = TrainingResult.model_validate(data)
        assert tr == tr2


class TestPlotRecord:
    def test_defaults(self) -> None:
        pr = PlotRecord(path="/tmp/plot.png", sha256="abc", title="CM")
        assert pr.plot_type == "confusion_matrix"


class TestReportRecord:
    def test_defaults(self) -> None:
        rr = ReportRecord(path="/tmp/report.md", sha256="def", title="Report")
        assert rr.sections == []


class TestEnvironmentSpec:
    def test_defaults(self) -> None:
        env = EnvironmentSpec(python_version="3.11.0", platform="linux")
        assert env.sklearn_version == ""
        assert env.matplotlib_version == ""


class TestReproducibilityRecord:
    def test_optional_nested(self) -> None:
        rec = ReproducibilityRecord(
            seed=42,
            dataset_checksum="abc",
            config_hash="def",
            environment_spec=EnvironmentSpec(
                python_version="3.11", platform="linux",
            ),
        )
        assert rec.dataset_record is None
        assert rec.training_result is None
        assert rec.plot_record is None
        assert rec.report_record is None

    def test_full_record(self) -> None:
        ds = DatasetRecord(
            name="iris", n_samples=150, n_features=4,
            n_classes=3, checksum="abc",
        )
        tr = TrainingResult(
            model_type="LR", metric_name="acc", metric_value=0.9,
            train_samples=120, test_samples=30,
            seed=42, duration_seconds=0.01,
        )
        rec = ReproducibilityRecord(
            seed=42,
            dataset_checksum="abc",
            config_hash="def",
            environment_spec=EnvironmentSpec(
                python_version="3.11", platform="linux",
            ),
            dataset_record=ds,
            training_result=tr,
        )
        data = rec.model_dump()
        rec2 = ReproducibilityRecord.model_validate(data)
        assert rec2.dataset_record.name == "iris"


class TestReviewResult:
    def test_passed(self) -> None:
        rr = ReviewResult(passed=True, summary="OK")
        assert rr.missing_fields == []
        assert rr.warnings == []


class TestToolIOSchemas:
    def test_dataset_input_output(self) -> None:
        cfg = ExperimentConfig()
        di = DatasetInput(config=cfg)
        assert di.config.dataset_name == "iris"

        dr = DatasetRecord(
            name="iris", n_samples=150, n_features=4,
            n_classes=3, checksum="abc",
        )
        do = DatasetOutput(record=dr)
        assert do.record.name == "iris"

    def test_python_runner_io(self) -> None:
        cfg = ExperimentConfig()
        dr = DatasetRecord(
            name="iris", n_samples=150, n_features=4,
            n_classes=3, checksum="abc",
        )
        pi = PythonRunnerInput(config=cfg, dataset_record=dr)
        assert pi.dataset_record.checksum == "abc"

        tr = TrainingResult(
            model_type="LR", metric_name="acc", metric_value=0.9,
            train_samples=120, test_samples=30,
            seed=42, duration_seconds=0.01,
        )
        po = PythonRunnerOutput(result=tr)
        assert po.result.metric_value == 0.9

    def test_reviewer_io(self) -> None:
        rec = ReproducibilityRecord(
            seed=42, dataset_checksum="abc", config_hash="def",
            environment_spec=EnvironmentSpec(
                python_version="3.11", platform="linux",
            ),
        )
        ri = ReviewerInput(reproducibility_record=rec)
        assert ri.reproducibility_record.seed == 42

        rr = ReviewResult(passed=True, summary="OK")
        ro = ReviewerOutput(result=rr)
        assert ro.result.passed
