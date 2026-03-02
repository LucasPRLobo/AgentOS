"""RLM Executor demo with a local Ollama Llama model.

Usage:
    python examples/rlm_ollama.py
    python examples/rlm_ollama.py --model llama3.1:8b --prompt "List the first 5 prime numbers"

Requires:
    - Ollama running locally (default: http://localhost:11434)
    - A pulled model (default: llama3.2:latest)
"""

from __future__ import annotations

import argparse
import json
import urllib.request
import urllib.error

from agentos.lm.provider import BaseLMProvider, LMMessage, LMResponse
from agentos.lm.recursive_executor import RecursiveExecutor, RLMConfig
from agentos.runtime.event_log import SQLiteEventLog


class OllamaProvider(BaseLMProvider):
    """Concrete LM provider backed by a local Ollama instance."""

    def __init__(self, model: str = "llama3.2:latest", base_url: str = "http://localhost:11434") -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")

    @property
    def name(self) -> str:
        return f"ollama-{self._model}"

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        payload = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
        }

        req = urllib.request.Request(
            f"{self._base_url}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )

        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())

        content = data["message"]["content"]
        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)

        return LMResponse(
            content=content,
            tokens_used=prompt_tokens + completion_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="RLM executor with Ollama")
    parser.add_argument("--model", default="llama3.2:latest", help="Ollama model name")
    parser.add_argument("--url", default="http://localhost:11434", help="Ollama base URL")
    parser.add_argument("--prompt", default="What are the first 5 Fibonacci numbers? Compute them step by step.", help="Prompt to process")
    parser.add_argument("--max-iterations", type=int, default=10, help="Max RLM iterations")
    args = parser.parse_args()

    # Verify Ollama is reachable
    try:
        urllib.request.urlopen(f"{args.url}/api/tags", timeout=5)
    except urllib.error.URLError:
        print(f"Error: Cannot reach Ollama at {args.url}")
        print("Start it with: ollama serve")
        return

    print(f"Model:  {args.model}")
    print(f"Prompt: {args.prompt}")
    print(f"Max iterations: {args.max_iterations}")
    print("-" * 60)

    provider = OllamaProvider(model=args.model, base_url=args.url)
    event_log = SQLiteEventLog()

    config = RLMConfig(
        max_iterations=args.max_iterations,
        max_recursion_depth=1,
        system_prompt=(
            "You are an RLM (Recursive Language Model) agent with a persistent Python REPL.\n"
            "The user's prompt is in variable P.\n"
            "You can call lm_query(text) to ask sub-questions to an LM.\n\n"
            "RULES:\n"
            "- Respond ONLY with Python code. No markdown, no explanation, no ```python blocks.\n"
            "- When done, assign your final answer string to FINAL.\n"
            "- Use print() to show intermediate results.\n"
            "- You have access to builtins like len, sorted, range, str, int, list, dict, etc.\n"
            "- No imports are available.\n"
        ),
    )

    run_id, result = executor_run(event_log, provider, args.prompt, config)

    # Print results
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
        label = e.event_type.value
        detail = ""
        p = e.payload
        if label == "RLMIterationStarted":
            detail = f"iteration={p.get('iteration')}"
        elif label == "LMCallFinished":
            detail = f"type={p.get('call_type')} tokens={p.get('tokens_used')}"
        elif label == "REPLExecFinished":
            detail = f"ok={p.get('success')} final={p.get('has_final')} vars={p.get('variables')}"
            if not p.get("success"):
                detail += f" err={p.get('error_type')}: {p.get('error_message')}"
        elif label == "RunFinished":
            detail = f"outcome={p.get('outcome')}"
        else:
            continue
        print(f"  [{e.seq:3d}] {label}: {detail}")


def executor_run(event_log, provider, prompt, config):
    """Run the executor with per-iteration output."""
    executor = RecursiveExecutor(event_log, provider)

    # We use the executor directly but print progress by checking events
    print("Starting RLM loop...\n")
    run_id, result = executor.run(prompt, config=config)

    # Print iteration details from the event log
    events = event_log.replay(run_id)
    iteration = 0
    for e in events:
        p = e.payload
        if e.event_type.value == "RLMIterationStarted":
            iteration = p.get("iteration", 0)
            print(f"--- Iteration {iteration} ---")
        elif e.event_type.value == "LMCallFinished" and p.get("call_type") == "code_generation":
            print(f"  LM generated {p.get('code_length')} chars ({p.get('tokens_used')} tokens)")
        elif e.event_type.value == "REPLExecFinished":
            if p.get("success"):
                print(f"  REPL: OK | vars={p.get('variables')}")
            else:
                print(f"  REPL: FAILED | {p.get('error_type')}: {p.get('error_message')}")
            if p.get("has_final"):
                print(f"  FINAL set!")
        elif e.event_type.value == "LMCallFinished" and p.get("call_type") == "sub_lm_query":
            print(f"  Sub-query: {p.get('tokens_used')} tokens")
    print()

    return run_id, result


if __name__ == "__main__":
    main()
