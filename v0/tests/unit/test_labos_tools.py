"""Tests for LabOS tools."""

import tempfile
from pathlib import Path

import pytest

from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.events import EventType
from agentos.tools.base import SideEffect

from labos.domain.schemas import (
    DatasetInput,
    DatasetRecord,
    EnvironmentSpec,
    ExperimentConfig,
    PlotInput,
    PythonRunnerInput,
    ReportInput,
    ReproducibilityRecord,
    ReviewerInput,
    TrainingResult,
)
from labos.tools._base import _SeqCounter, execute_with_events
from labos.tools.dataset import DatasetTool
from labos.tools.plot import PlotTool
from labos.tools.python_runner import PythonRunnerTool
from labos.tools.report import ReportTool
from labos.tools.reviewer import ReviewerTool


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear DatasetTool cache before and after each test."""
    DatasetTool.clear_cache()
    yield
    DatasetTool.clear_cache()


class TestDatasetTool:
    def test_load_iris(self) -> None:
        tool = DatasetTool()
        assert tool.name == "dataset_loader"
        assert tool.side_effect == SideEffect.READ

        out = tool.execute(DatasetInput(config=ExperimentConfig(dataset_name="iris")))
        rec = out.record
        assert rec.name == "iris"
        assert rec.n_samples == 150
        assert rec.n_features == 4
        assert rec.n_classes == 3
        assert len(rec.checksum) == 64  # SHA-256 hex

    def test_load_synthetic(self) -> None:
        tool = DatasetTool()
        cfg = ExperimentConfig(
            dataset_name="synthetic",
            model_params={"n_samples": 100, "n_features": 5, "n_classes": 2},
        )
        out = tool.execute(DatasetInput(config=cfg))
        assert out.record.name == "synthetic"
        assert out.record.n_samples == 100
        assert out.record.n_features == 5

    def test_unknown_dataset(self) -> None:
        tool = DatasetTool()
        with pytest.raises(ValueError, match="Unknown dataset"):
            tool.execute(DatasetInput(config=ExperimentConfig(dataset_name="unknown")))

    def test_cache(self) -> None:
        tool = DatasetTool()
        tool.execute(DatasetInput(config=ExperimentConfig(dataset_name="iris")))
        X, y = DatasetTool.get_cached_data("iris")
        assert X.shape == (150, 4)
        assert len(y) == 150

    def test_cache_miss(self) -> None:
        with pytest.raises(KeyError):
            DatasetTool.get_cached_data("nonexistent")

    def test_deterministic_checksum(self) -> None:
        tool = DatasetTool()
        out1 = tool.execute(DatasetInput(config=ExperimentConfig()))
        out2 = tool.execute(DatasetInput(config=ExperimentConfig()))
        assert out1.record.checksum == out2.record.checksum


class TestPythonRunnerTool:
    def test_train_iris(self) -> None:
        tool = PythonRunnerTool()
        assert tool.name == "python_runner"
        assert tool.side_effect == SideEffect.PURE

        # Load dataset first
        DatasetTool().execute(DatasetInput(config=ExperimentConfig()))

        config = ExperimentConfig()
        ds_rec = DatasetRecord(
            name="iris", n_samples=150, n_features=4,
            n_classes=3, checksum="test",
        )
        out = tool.execute(PythonRunnerInput(config=config, dataset_record=ds_rec))
        assert out.result.model_type == "LogisticRegression"
        assert out.result.metric_name == "accuracy"
        assert 0.0 <= out.result.metric_value <= 1.0
        assert out.result.seed == 42
        assert out.result.train_samples + out.result.test_samples == 150

    def test_unknown_model(self) -> None:
        DatasetTool().execute(DatasetInput(config=ExperimentConfig()))
        tool = PythonRunnerTool()
        cfg = ExperimentConfig(model_type="UnknownModel")
        ds_rec = DatasetRecord(
            name="iris", n_samples=150, n_features=4,
            n_classes=3, checksum="test",
        )
        with pytest.raises(ValueError, match="Unknown model type"):
            tool.execute(PythonRunnerInput(config=cfg, dataset_record=ds_rec))

    def test_deterministic_training(self) -> None:
        DatasetTool().execute(DatasetInput(config=ExperimentConfig()))
        tool = PythonRunnerTool()
        config = ExperimentConfig()
        ds_rec = DatasetRecord(
            name="iris", n_samples=150, n_features=4,
            n_classes=3, checksum="test",
        )
        out1 = tool.execute(PythonRunnerInput(config=config, dataset_record=ds_rec))
        out2 = tool.execute(PythonRunnerInput(config=config, dataset_record=ds_rec))
        assert out1.result.metric_value == out2.result.metric_value


class TestPlotTool:
    def test_generate_plot(self) -> None:
        DatasetTool().execute(DatasetInput(config=ExperimentConfig()))
        tool = PlotTool()
        assert tool.name == "plot_generator"
        assert tool.side_effect == SideEffect.WRITE

        config = ExperimentConfig()
        ds_rec = DatasetRecord(
            name="iris", n_samples=150, n_features=4,
            n_classes=3, target_names=["setosa", "versicolor", "virginica"],
            checksum="test",
        )
        tr = TrainingResult(
            model_type="LogisticRegression", metric_name="accuracy",
            metric_value=0.95, train_samples=120, test_samples=30,
            seed=42, duration_seconds=0.01,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            out = tool.execute(PlotInput(
                config=config, dataset_record=ds_rec,
                training_result=tr, output_dir=tmpdir,
            ))
            assert out.record.plot_type == "confusion_matrix"
            assert Path(out.record.path).exists()
            assert len(out.record.sha256) == 64


class TestReportTool:
    def test_generate_report(self) -> None:
        tool = ReportTool()
        assert tool.name == "report_generator"
        assert tool.side_effect == SideEffect.WRITE

        config = ExperimentConfig()
        ds_rec = DatasetRecord(
            name="iris", n_samples=150, n_features=4,
            n_classes=3, checksum="test",
        )
        tr = TrainingResult(
            model_type="LogisticRegression", metric_name="accuracy",
            metric_value=0.95, train_samples=120, test_samples=30,
            seed=42, duration_seconds=0.01,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            out = tool.execute(ReportInput(
                config=config, dataset_record=ds_rec,
                training_result=tr, output_dir=tmpdir,
            ))
            assert "Summary" in out.record.sections
            assert "Results" in out.record.sections
            assert Path(out.record.path).exists()

            content = Path(out.record.path).read_text()
            assert "LogisticRegression" in content
            assert "0.9500" in content

    def test_report_with_plot(self) -> None:
        tool = ReportTool()
        config = ExperimentConfig()
        ds_rec = DatasetRecord(
            name="iris", n_samples=150, n_features=4,
            n_classes=3, checksum="test",
        )
        tr = TrainingResult(
            model_type="LR", metric_name="acc", metric_value=0.9,
            train_samples=120, test_samples=30,
            seed=42, duration_seconds=0.01,
        )
        from labos.domain.schemas import PlotRecord
        pr = PlotRecord(path="plot.png", sha256="abc", title="CM")

        with tempfile.TemporaryDirectory() as tmpdir:
            out = tool.execute(ReportInput(
                config=config, dataset_record=ds_rec,
                training_result=tr, plot_record=pr, output_dir=tmpdir,
            ))
            assert "Visualizations" in out.record.sections


class TestReviewerTool:
    def test_valid_record(self) -> None:
        tool = ReviewerTool()
        assert tool.name == "reviewer"
        assert tool.side_effect == SideEffect.PURE

        rec = ReproducibilityRecord(
            seed=42, dataset_checksum="abc", config_hash="def",
            environment_spec=EnvironmentSpec(
                python_version="3.11", platform="linux",
                sklearn_version="1.3",
            ),
            dataset_record=DatasetRecord(
                name="iris", n_samples=150, n_features=4,
                n_classes=3, checksum="abc",
            ),
        )
        out = tool.execute(ReviewerInput(reproducibility_record=rec))
        assert out.result.passed
        assert len(out.result.missing_fields) == 0

    def test_empty_checksum_fails(self) -> None:
        tool = ReviewerTool()
        rec = ReproducibilityRecord(
            seed=42, dataset_checksum="", config_hash="def",
            environment_spec=EnvironmentSpec(
                python_version="3.11", platform="linux",
            ),
        )
        out = tool.execute(ReviewerInput(reproducibility_record=rec))
        assert not out.result.passed
        assert "dataset_checksum" in out.result.missing_fields

    def test_warnings(self) -> None:
        tool = ReviewerTool()
        rec = ReproducibilityRecord(
            seed=42, dataset_checksum="abc", config_hash="def",
            environment_spec=EnvironmentSpec(
                python_version="3.11", platform="linux",
            ),
        )
        out = tool.execute(ReviewerInput(reproducibility_record=rec))
        # Should warn about empty sklearn_version, code_version, no plot, no report
        assert out.result.passed
        assert len(out.result.warnings) > 0


class TestExecuteWithEvents:
    def test_emits_events(self) -> None:
        event_log = SQLiteEventLog()
        from agentos.core.identifiers import generate_run_id

        run_id = generate_run_id()
        seq = _SeqCounter(0)

        tool = ReviewerTool()
        rec = ReproducibilityRecord(
            seed=42, dataset_checksum="abc", config_hash="def",
            environment_spec=EnvironmentSpec(
                python_version="3.11", platform="linux",
            ),
        )
        execute_with_events(
            tool,
            ReviewerInput(reproducibility_record=rec),
            event_log, run_id, seq,
        )

        events = event_log.query_by_run(run_id)
        assert len(events) == 2
        assert events[0].event_type == EventType.TOOL_CALL_STARTED
        assert events[0].payload["tool_name"] == "reviewer"
        assert events[1].event_type == EventType.TOOL_CALL_FINISHED
        assert events[1].payload["success"] is True

    def test_emits_failure_event(self) -> None:
        event_log = SQLiteEventLog()
        from agentos.core.identifiers import generate_run_id

        run_id = generate_run_id()
        seq = _SeqCounter(0)

        tool = DatasetTool()
        with pytest.raises(ValueError):
            execute_with_events(
                tool,
                DatasetInput(config=ExperimentConfig(dataset_name="bad")),
                event_log, run_id, seq,
            )

        events = event_log.query_by_run(run_id)
        assert len(events) == 2
        assert events[1].event_type == EventType.TOOL_CALL_FINISHED
        assert events[1].payload["success"] is False
