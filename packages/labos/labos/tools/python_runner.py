"""PythonRunnerTool — trains and evaluates sklearn models."""

from __future__ import annotations

import time

from pydantic import BaseModel
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

from agentos.tools.base import BaseTool, SideEffect

from labos.domain.schemas import PythonRunnerInput, PythonRunnerOutput, TrainingResult
from labos.tools.dataset import DatasetTool

# Supported model types
MODEL_REGISTRY: dict[str, type] = {
    "LogisticRegression": LogisticRegression,
}


class PythonRunnerTool(BaseTool):
    """Train an sklearn model on a cached dataset and evaluate accuracy."""

    @property
    def name(self) -> str:
        return "python_runner"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return PythonRunnerInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return PythonRunnerOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.PURE

    def execute(self, input_data: BaseModel) -> BaseModel:
        data = input_data if isinstance(input_data, PythonRunnerInput) else PythonRunnerInput.model_validate(input_data.model_dump())
        config = data.config

        if config.model_type not in MODEL_REGISTRY:
            raise ValueError(
                f"Unknown model type: {config.model_type}. "
                f"Available: {list(MODEL_REGISTRY.keys())}"
            )

        X, y = DatasetTool.get_cached_data(config.dataset_name)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y,
            test_size=config.test_size,
            random_state=config.random_seed,
            stratify=y,
        )

        model_cls = MODEL_REGISTRY[config.model_type]
        model_params = dict(config.model_params)
        model_params.setdefault("random_state", config.random_seed)
        model_params.setdefault("max_iter", 200)

        start = time.monotonic()
        model = model_cls(**model_params)
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)
        duration = time.monotonic() - start

        metric_value = accuracy_score(y_test, y_pred)

        result = TrainingResult(
            model_type=config.model_type,
            model_params=model_params,
            metric_name=config.metric_name,
            metric_value=metric_value,
            train_samples=len(X_train),
            test_samples=len(X_test),
            seed=config.random_seed,
            duration_seconds=duration,
        )
        return PythonRunnerOutput(result=result)
