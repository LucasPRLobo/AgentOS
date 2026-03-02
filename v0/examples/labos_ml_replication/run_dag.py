"""Deterministic ML replication demo using the DAG executor.

Usage:
    python examples/labos_ml_replication/run_dag.py
    python examples/labos_ml_replication/run_dag.py --dataset iris --seed 42

Produces:
    - confusion_matrix.png
    - report.md
    - Event log trace
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.events import EventType

from labos.domain.schemas import ExperimentConfig
from labos.tools.dataset import DatasetTool
from labos.workflows.ml_replication import run_dag_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="LabOS DAG ML replication")
    parser.add_argument("--dataset", default="iris", help="Dataset name (iris, synthetic)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--output-dir", default=None, help="Output directory (default: tempdir)")
    args = parser.parse_args()

    config = ExperimentConfig(
        dataset_name=args.dataset,
        random_seed=args.seed,
    )

    output_dir = args.output_dir or tempfile.mkdtemp(prefix="labos_dag_")
    event_log = SQLiteEventLog()

    print(f"Config: {config.model_dump()}")
    print(f"Output: {output_dir}")
    print("-" * 60)

    DatasetTool.clear_cache()
    run_id = run_dag_pipeline(config, event_log=event_log, output_dir=output_dir)

    print(f"\nRun ID: {run_id}")

    # Print event trace
    events = event_log.replay(run_id)
    print(f"Total events: {len(events)}")
    print()

    for e in events:
        p = e.payload
        label = e.event_type.value

        if e.event_type == EventType.TASK_STARTED:
            print(f"  [{e.seq:3d}] TASK START: {p.get('task_name')}")
        elif e.event_type == EventType.TASK_FINISHED:
            print(f"  [{e.seq:3d}] TASK END:   {p.get('task_name')} → {p.get('state')}")
        elif e.event_type == EventType.TOOL_CALL_STARTED:
            print(f"  [{e.seq:3d}]   TOOL START: {p.get('tool_name')} (v{p.get('tool_version')})")
        elif e.event_type == EventType.TOOL_CALL_FINISHED:
            status = "OK" if p.get("success") else f"FAIL: {p.get('error')}"
            print(f"  [{e.seq:3d}]   TOOL END:   {p.get('tool_name')} → {status}")
        elif e.event_type == EventType.RUN_FINISHED:
            print(f"  [{e.seq:3d}] RUN FINISHED: {p.get('outcome')}")

    # List output files
    print()
    out = Path(output_dir)
    for f in sorted(out.iterdir()):
        print(f"  {f.name} ({f.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
