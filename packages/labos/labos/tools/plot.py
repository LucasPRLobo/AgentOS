"""PlotTool — generates confusion matrix plots."""

from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np
from pydantic import BaseModel
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import train_test_split

from agentos.integrity.hashing import hash_file
from agentos.tools.base import BaseTool, SideEffect

from labos.domain.schemas import PlotInput, PlotOutput, PlotRecord
from labos.tools.dataset import DatasetTool
from labos.tools.python_runner import MODEL_REGISTRY

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


class PlotTool(BaseTool):
    """Generate a confusion matrix PNG from experiment results."""

    @property
    def name(self) -> str:
        return "plot_generator"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return PlotInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return PlotOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.WRITE

    def execute(self, input_data: BaseModel) -> BaseModel:
        data = input_data if isinstance(input_data, PlotInput) else PlotInput.model_validate(input_data.model_dump())
        config = data.config
        dataset_record = data.dataset_record
        output_dir = Path(data.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Re-train model deterministically to get predictions
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
        model = model_cls(**model_params)
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)

        # Generate confusion matrix plot
        cm = confusion_matrix(y_test, y_pred)
        title = f"Confusion Matrix — {config.model_type} on {dataset_record.name}"

        fig, ax = plt.subplots(figsize=(8, 6))
        im = ax.imshow(cm, interpolation="nearest", cmap=plt.cm.Blues)
        ax.set_title(title)
        fig.colorbar(im, ax=ax)

        classes = dataset_record.target_names or [str(i) for i in range(len(cm))]
        tick_marks = np.arange(len(classes))
        ax.set_xticks(tick_marks)
        ax.set_xticklabels(classes, rotation=45, ha="right")
        ax.set_yticks(tick_marks)
        ax.set_yticklabels(classes)

        # Add text annotations
        thresh = cm.max() / 2.0
        for i in range(cm.shape[0]):
            for j in range(cm.shape[1]):
                ax.text(
                    j, i, str(cm[i, j]),
                    ha="center", va="center",
                    color="white" if cm[i, j] > thresh else "black",
                )

        ax.set_ylabel("True label")
        ax.set_xlabel("Predicted label")
        fig.tight_layout()

        plot_path = output_dir / "confusion_matrix.png"
        fig.savefig(str(plot_path), dpi=100)
        plt.close(fig)

        sha = hash_file(plot_path)

        record = PlotRecord(
            path=str(plot_path),
            sha256=sha,
            title=title,
            plot_type="confusion_matrix",
        )
        return PlotOutput(record=record)
