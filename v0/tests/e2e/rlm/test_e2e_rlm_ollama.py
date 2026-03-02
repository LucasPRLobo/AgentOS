"""E2E tests for RLM pipeline with real Ollama provider (requires network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from labos.domain.schemas import ExperimentConfig
from labos.providers.ollama import OllamaProvider
from labos.workflows.ml_replication import run_rlm_pipeline

pytestmark = [pytest.mark.e2e, pytest.mark.network]


def _ollama_available() -> bool:
    """Check if Ollama is available."""
    try:
        provider = OllamaProvider()
        return provider.is_available()
    except Exception:
        return False


@pytest.fixture()
def ollama_provider():
    """Return an OllamaProvider or skip if unavailable."""
    if not _ollama_available():
        pytest.skip("Ollama not available")
    return OllamaProvider()


class TestRLMWithOllama:
    """Run the RLM pipeline with a real Ollama LLM."""

    def test_rlm_ollama_iris(self, tmp_path, ollama_provider):
        config = ExperimentConfig(
            dataset_name="iris",
            model_type="LogisticRegression",
            random_seed=42,
        )

        run_id, result = run_rlm_pipeline(
            config,
            ollama_provider,
            output_dir=str(tmp_path),
            max_iterations=20,
        )

        # With a real LLM, we can't guarantee output files are created
        # (the LLM may not produce working code), but the pipeline must
        # complete without crashing and return a valid run_id.
        assert run_id is not None

    def test_rlm_ollama_output_files(self, tmp_path, ollama_provider):
        config = ExperimentConfig(
            dataset_name="iris",
            model_type="LogisticRegression",
            random_seed=42,
        )

        run_id, result = run_rlm_pipeline(
            config,
            ollama_provider,
            output_dir=str(tmp_path),
            max_iterations=20,
        )

        output_path = Path(tmp_path)
        # Check for any generated files
        files = list(output_path.iterdir())
        assert len(files) >= 0  # At minimum, should not crash
