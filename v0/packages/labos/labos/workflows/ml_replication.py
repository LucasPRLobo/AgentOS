"""ML replication workflows — DAG and RLM execution paths."""

from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Any

import matplotlib
import sklearn

from agentos.core.identifiers import RunId, generate_run_id
from agentos.integrity.hashing import hash_dict
from agentos.lm.provider import BaseLMProvider
from agentos.lm.recursive_executor import RLMConfig, RecursiveExecutor
from agentos.runtime.dag import DAGWorkflow
from agentos.runtime.event_log import EventLog, SQLiteEventLog
from agentos.runtime.task import TaskNode
from agentos.schemas.budget import BudgetSpec

from labos.domain.schemas import (
    DatasetInput,
    EnvironmentSpec,
    ExperimentConfig,
    PlotInput,
    PythonRunnerInput,
    ReportInput,
    ReproducibilityRecord,
    ReviewerInput,
)
from labos.tools._base import _SeqCounter, execute_with_events
from labos.tools.dataset import DatasetTool
from labos.tools.plot import PlotTool
from labos.tools.python_runner import PythonRunnerTool
from labos.tools.report import ReportTool
from labos.tools.reviewer import ReviewerTool


def _get_environment_spec() -> EnvironmentSpec:
    """Capture the current runtime environment."""
    from datetime import UTC, datetime

    return EnvironmentSpec(
        python_version=sys.version,
        platform=platform.platform(),
        sklearn_version=sklearn.__version__,
        matplotlib_version=matplotlib.__version__,
        timestamp=datetime.now(UTC).isoformat(),
    )


# ── DAG path ────────────────────────────────────────────────────────


def build_dag_workflow(
    config: ExperimentConfig,
    event_log: EventLog,
    run_id: RunId,
    seq_counter: _SeqCounter,
    output_dir: str = ".",
) -> DAGWorkflow:
    """Build the 6-step ML replication DAG.

    Uses closure-captured shared state to pass data between task callables
    (since ``TaskNode.callable()`` takes zero args).
    """
    state: dict[str, Any] = {}

    dataset_tool = DatasetTool()
    runner_tool = PythonRunnerTool()
    plot_tool = PlotTool()
    report_tool = ReportTool()
    reviewer_tool = ReviewerTool()

    def define_question() -> str:
        state["question"] = (
            f"Can we replicate {config.model_type} on {config.dataset_name} "
            f"with seed={config.random_seed}?"
        )
        return state["question"]

    def design_experiment() -> dict[str, Any]:
        state["config_hash"] = hash_dict(config.model_dump())
        state["env_spec"] = _get_environment_spec()
        state["code_version"] = ""
        return {"config_hash": state["config_hash"]}

    def run_experiment() -> None:
        ds_out = execute_with_events(
            dataset_tool,
            DatasetInput(config=config),
            event_log, run_id, seq_counter,
        )
        state["dataset_record"] = ds_out.record

        runner_out = execute_with_events(
            runner_tool,
            PythonRunnerInput(config=config, dataset_record=ds_out.record),
            event_log, run_id, seq_counter,
        )
        state["training_result"] = runner_out.result

    def analyze_results() -> None:
        plot_out = execute_with_events(
            plot_tool,
            PlotInput(
                config=config,
                dataset_record=state["dataset_record"],
                training_result=state["training_result"],
                output_dir=output_dir,
            ),
            event_log, run_id, seq_counter,
        )
        state["plot_record"] = plot_out.record

    def write_report() -> None:
        report_out = execute_with_events(
            report_tool,
            ReportInput(
                config=config,
                dataset_record=state["dataset_record"],
                training_result=state["training_result"],
                plot_record=state["plot_record"],
                output_dir=output_dir,
            ),
            event_log, run_id, seq_counter,
        )
        state["report_record"] = report_out.record

    def reviewer_check() -> None:
        repro = ReproducibilityRecord(
            seed=config.random_seed,
            dataset_checksum=state["dataset_record"].checksum,
            config_hash=state["config_hash"],
            environment_spec=state["env_spec"],
            code_version=state.get("code_version", ""),
            dataset_record=state["dataset_record"],
            training_result=state["training_result"],
            plot_record=state.get("plot_record"),
            report_record=state.get("report_record"),
        )
        review_out = execute_with_events(
            reviewer_tool,
            ReviewerInput(reproducibility_record=repro),
            event_log, run_id, seq_counter,
        )
        state["review_result"] = review_out.result

    # Build task nodes with dependencies
    t1 = TaskNode(name="DefineQuestion", callable=define_question)
    t2 = TaskNode(name="DesignExperiment", callable=design_experiment, depends_on=[t1])
    t3 = TaskNode(name="RunExperiment", callable=run_experiment, depends_on=[t2])
    t4 = TaskNode(name="AnalyzeResults", callable=analyze_results, depends_on=[t3])
    t5 = TaskNode(name="WriteReport", callable=write_report, depends_on=[t4])
    t6 = TaskNode(name="ReviewerCheck", callable=reviewer_check, depends_on=[t5])

    dag = DAGWorkflow(name="ml_replication", tasks=[t1, t2, t3, t4, t5, t6])
    return dag


def run_dag_pipeline(
    config: ExperimentConfig,
    *,
    event_log: EventLog | None = None,
    output_dir: str | None = None,
    run_id: RunId | None = None,
) -> RunId:
    """Run the full ML replication pipeline as a sequential DAG.

    Builds the DAG for validation and topological ordering, then executes
    tasks sequentially with a single shared sequence counter so that
    RunStarted/TaskStarted/ToolCallStarted events all use non-conflicting
    sequence numbers.

    Returns the run ID.
    """
    from agentos.schemas.events import RunFinished, RunStarted, TaskFinished, TaskStarted

    el = event_log or SQLiteEventLog()
    rid = run_id or generate_run_id()
    out = output_dir or "."
    Path(out).mkdir(parents=True, exist_ok=True)

    seq = _SeqCounter(0)
    dag = build_dag_workflow(config, el, rid, seq, output_dir=out)
    dag.validate()
    ordered = dag.topological_order()

    el.append(RunStarted(
        run_id=rid, seq=seq.next(),
        payload={"workflow": dag.name},
    ))

    for task in ordered:
        el.append(TaskStarted(
            run_id=rid, seq=seq.next(),
            payload={"task_id": task.id, "task_name": task.name},
        ))
        try:
            task.callable()
            state_str = "SUCCEEDED"
        except Exception as exc:
            state_str = "FAILED"
            el.append(TaskFinished(
                run_id=rid, seq=seq.next(),
                payload={"task_id": task.id, "task_name": task.name,
                         "state": state_str, "error": str(exc)},
            ))
            el.append(RunFinished(
                run_id=rid, seq=seq.next(),
                payload={"workflow": dag.name, "outcome": "FAILED",
                         "failed_tasks": [task.name]},
            ))
            raise
        el.append(TaskFinished(
            run_id=rid, seq=seq.next(),
            payload={"task_id": task.id, "task_name": task.name,
                     "state": state_str},
        ))

    el.append(RunFinished(
        run_id=rid, seq=seq.next(),
        payload={"workflow": dag.name, "outcome": "SUCCEEDED"},
    ))
    return rid


# ── RLM path ────────────────────────────────────────────────────────


_RLM_SYSTEM_PROMPT = """\
You are an RLM (Recursive Language Model) agent replicating an ML experiment.
The user's prompt is in variable P. The experiment config is in CONFIG (a dict).

You have these functions available (pre-injected, NO imports needed):
- load_dataset() -> dict: Load the dataset per CONFIG. Returns the dataset record as a dict.
- train_model(dataset_record: dict) -> dict: Train the model. Returns the training result as a dict.
- generate_plot(dataset_record: dict, training_result: dict) -> dict: Generate a confusion matrix plot. Returns the plot record as a dict.
- generate_report(dataset_record: dict, training_result: dict, plot_record: dict | None) -> dict: Generate a markdown report. Returns the report record as a dict.
- review_run(dataset_record: dict, training_result: dict, plot_record: dict | None, report_record: dict | None) -> dict: Validate reproducibility. Returns the review result as a dict.

Workflow steps:
1. Call load_dataset() to get the dataset record.
2. Call train_model(dataset_record) to train and evaluate the model.
3. Call generate_plot(dataset_record, training_result) to create a confusion matrix.
4. Call generate_report(dataset_record, training_result, plot_record) to write a report.
5. Call review_run(dataset_record, training_result, plot_record, report_record) to validate.
6. Set FINAL to a summary string of the results.

RULES:
- Respond ONLY with Python code. No markdown, no explanation, no ```python blocks.
- No imports are available. All tools are pre-injected functions.
- Use print() to show intermediate results.
- When done, assign your final answer string to FINAL.
"""


def run_rlm_pipeline(
    config: ExperimentConfig,
    lm_provider: BaseLMProvider,
    *,
    event_log: EventLog | None = None,
    output_dir: str | None = None,
    budget_spec: BudgetSpec | None = None,
    max_iterations: int = 20,
) -> tuple[RunId, str | None]:
    """Run the ML replication pipeline via the RLM executor.

    The LLM generates Python code that calls the pre-injected tool wrapper
    functions in a sandboxed REPL.

    Returns (run_id, final_result).
    """
    el = event_log or SQLiteEventLog()
    out = output_dir or "."
    Path(out).mkdir(parents=True, exist_ok=True)

    # Instantiate tools
    dataset_tool = DatasetTool()
    runner_tool = PythonRunnerTool()
    plot_tool = PlotTool()
    report_tool = ReportTool()
    reviewer_tool = ReviewerTool()

    config_hash = hash_dict(config.model_dump())
    env_spec = _get_environment_spec()

    # Build wrapper functions that the LLM-generated code can call
    def load_dataset() -> dict[str, Any]:
        output = dataset_tool.execute(DatasetInput(config=config))
        return output.record.model_dump()

    def train_model(dataset_record: dict[str, Any]) -> dict[str, Any]:
        from labos.domain.schemas import DatasetRecord

        dr = DatasetRecord.model_validate(dataset_record)
        output = runner_tool.execute(PythonRunnerInput(config=config, dataset_record=dr))
        return output.result.model_dump()

    def generate_plot(
        dataset_record: dict[str, Any],
        training_result: dict[str, Any],
    ) -> dict[str, Any]:
        from labos.domain.schemas import DatasetRecord, TrainingResult

        dr = DatasetRecord.model_validate(dataset_record)
        tr = TrainingResult.model_validate(training_result)
        output = plot_tool.execute(
            PlotInput(config=config, dataset_record=dr, training_result=tr, output_dir=out)
        )
        return output.record.model_dump()

    def generate_report(
        dataset_record: dict[str, Any],
        training_result: dict[str, Any],
        plot_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from labos.domain.schemas import DatasetRecord, PlotRecord, TrainingResult

        dr = DatasetRecord.model_validate(dataset_record)
        tr = TrainingResult.model_validate(training_result)
        pr = PlotRecord.model_validate(plot_record) if plot_record else None
        output = report_tool.execute(
            ReportInput(config=config, dataset_record=dr, training_result=tr, plot_record=pr, output_dir=out)
        )
        return output.record.model_dump()

    def review_run(
        dataset_record: dict[str, Any],
        training_result: dict[str, Any],
        plot_record: dict[str, Any] | None = None,
        report_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from labos.domain.schemas import (
            DatasetRecord,
            PlotRecord,
            ReportRecord,
            TrainingResult,
        )

        dr = DatasetRecord.model_validate(dataset_record)
        tr = TrainingResult.model_validate(training_result)
        pr = PlotRecord.model_validate(plot_record) if plot_record else None
        rr = ReportRecord.model_validate(report_record) if report_record else None

        repro = ReproducibilityRecord(
            seed=config.random_seed,
            dataset_checksum=dr.checksum,
            config_hash=config_hash,
            environment_spec=env_spec,
            code_version="",
            dataset_record=dr,
            training_result=tr,
            plot_record=pr,
            report_record=rr,
        )
        output = reviewer_tool.execute(ReviewerInput(reproducibility_record=repro))
        return output.result.model_dump()

    # Set up budget manager if spec provided
    budget_manager = None
    if budget_spec:
        from agentos.governance.budget_manager import BudgetManager

        rid = generate_run_id()
        budget_manager = BudgetManager(budget_spec, el, rid)

    rlm_config = RLMConfig(
        system_prompt=_RLM_SYSTEM_PROMPT,
        max_iterations=max_iterations,
        max_recursion_depth=1,
    )

    executor = RecursiveExecutor(
        el, lm_provider,
        budget_manager=budget_manager,
    )

    prompt = (
        f"Replicate the ML experiment described in CONFIG. "
        f"Dataset: {config.dataset_name}, Model: {config.model_type}, "
        f"Seed: {config.random_seed}."
    )

    run_id, result = executor.run(
        prompt,
        config=rlm_config,
        extra_vars={"CONFIG": config.model_dump()},
        extra_functions={
            "load_dataset": load_dataset,
            "train_model": train_model,
            "generate_plot": generate_plot,
            "generate_report": generate_report,
            "review_run": review_run,
        },
    )

    return run_id, result
