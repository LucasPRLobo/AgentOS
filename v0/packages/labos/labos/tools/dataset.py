"""DatasetTool — loads and checksums ML datasets."""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
from pydantic import BaseModel
from sklearn.datasets import load_iris, make_classification

from agentos.tools.base import BaseTool, SideEffect

from labos.domain.schemas import DatasetInput, DatasetOutput, DatasetRecord


class DatasetTool(BaseTool):
    """Load a dataset and compute a reproducibility checksum.

    Supports 'iris' (sklearn load_iris) and 'synthetic' (make_classification).
    Caches loaded arrays at the class level for downstream tools.
    """

    _cache: dict[str, tuple[Any, Any]] = {}

    @property
    def name(self) -> str:
        return "dataset_loader"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return DatasetInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return DatasetOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.READ

    def execute(self, input_data: BaseModel) -> BaseModel:
        data = input_data if isinstance(input_data, DatasetInput) else DatasetInput.model_validate(input_data.model_dump())
        config = data.config
        dataset_name = config.dataset_name

        if dataset_name == "iris":
            ds = load_iris()
            X, y = ds.data, ds.target
            feature_names = list(ds.feature_names)
            target_names = list(ds.target_names)
        elif dataset_name == "synthetic":
            n_samples = config.model_params.get("n_samples", 200)
            n_features = config.model_params.get("n_features", 10)
            n_classes = config.model_params.get("n_classes", 3)
            X, y = make_classification(
                n_samples=n_samples,
                n_features=n_features,
                n_informative=max(2, n_features // 2),
                n_classes=n_classes,
                random_state=config.random_seed,
            )
            feature_names = [f"feature_{i}" for i in range(n_features)]
            target_names = [f"class_{i}" for i in range(n_classes)]
        else:
            raise ValueError(f"Unknown dataset: {dataset_name}")

        # Compute deterministic checksum
        checksum = self._compute_checksum(X, y)

        # Cache for downstream tools
        DatasetTool._cache[dataset_name] = (X, y)

        n_classes_actual = len(np.unique(y))
        record = DatasetRecord(
            name=dataset_name,
            n_samples=X.shape[0],
            n_features=X.shape[1],
            n_classes=n_classes_actual,
            feature_names=feature_names,
            target_names=target_names,
            checksum=checksum,
        )
        return DatasetOutput(record=record)

    @staticmethod
    def _compute_checksum(X: Any, y: Any) -> str:
        h = hashlib.sha256()
        h.update(np.asarray(X).tobytes())
        h.update(np.asarray(y).tobytes())
        return h.hexdigest()

    @classmethod
    def get_cached_data(cls, dataset_name: str) -> tuple[Any, Any]:
        """Retrieve cached (X, y) arrays for the given dataset."""
        if dataset_name not in cls._cache:
            raise KeyError(f"Dataset '{dataset_name}' not loaded. Run DatasetTool first.")
        return cls._cache[dataset_name]

    @classmethod
    def clear_cache(cls) -> None:
        """Clear all cached data."""
        cls._cache.clear()
