"""LLM agent ML replication demo using the RLM executor with Ollama.

Usage:
    python examples/labos_ml_replication/run_rlm.py
    python examples/labos_ml_replication/run_rlm.py --model llama3.2:latest --seed 42

Requires:
    - Ollama running locally (default: http://localhost:11434)
    - A pulled model (default: llama3.2:latest)
"""

from __future__ import annotations

import argparse
import tempfile

from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.events import EventType

from labos.domain.schemas import ExperimentConfig
from labos.providers.ollama import OllamaProvider
from labos.tools.dataset import DatasetTool
from labos.workflows.ml_replication import run_rlm_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="LabOS RLM ML replication")
    parser.add_argument("--model", default="llama3.2:latest", help="Ollama model name")
    parser.add_argument("--url", default="http://localhost:11434", help="Ollama base URL")
    parser.add_argument("--dataset", default="iris", help="Dataset name")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--max-iterations", type=int, default=20, help="Max RLM iterations")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    args = parser.parse_args()

    provider = OllamaProvider(model=args.model, base_url=args.url)
    if not provider.is_available():
        print(f"Error: Cannot reach Ollama at {args.url}")
        print("Start it with: ollama serve")
        return

    config = ExperimentConfig(
        dataset_name=args.dataset,
        random_seed=args.seed,
    )

    output_dir = args.output_dir or tempfile.mkdtemp(prefix="labos_rlm_")
    event_log = SQLiteEventLog()

    print(f"Model:  {args.model}")
    print(f"Config: {config.model_dump()}")
    print(f"Output: {output_dir}")
    print("-" * 60)

    DatasetTool.clear_cache()
    run_id, result = run_rlm_pipeline(
        config, provider,
        event_log=event_log,
        output_dir=output_dir,
        max_iterations=args.max_iterations,
    )

    print("-" * 60)
    print(f"Run ID: {run_id}")
    print(f"Final result: {result}")
    print()

    # Print event summary
    events = event_log.replay(run_id)
    print(f"Total events: {len(events)}")
    print()
    print("Event trace:")
    for e in events:
        p = e.payload
        label = e.event_type.value
        if e.event_type == EventType.RLM_ITERATION_STARTED:
            print(f"  [{e.seq:3d}] Iteration {p.get('iteration')}")
        elif e.event_type == EventType.LM_CALL_FINISHED:
            print(f"  [{e.seq:3d}]   LM: type={p.get('call_type')} tokens={p.get('tokens_used')}")
        elif e.event_type == EventType.REPL_EXEC_FINISHED:
            status = "OK" if p.get("success") else f"ERR: {p.get('error_type')}"
            final = " [FINAL]" if p.get("has_final") else ""
            print(f"  [{e.seq:3d}]   REPL: {status}{final}")
        elif e.event_type == EventType.RUN_FINISHED:
            print(f"  [{e.seq:3d}] RUN FINISHED: {p.get('outcome')}")


if __name__ == "__main__":
    main()
