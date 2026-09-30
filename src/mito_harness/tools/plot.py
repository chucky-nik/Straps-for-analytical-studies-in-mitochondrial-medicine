"""Песочница визуализации: рейтинг направлений с safety-цветами по label."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from mito_harness.config import settings
from mito_harness.schemas import DirectionLabel, DirectionScore


_COLORS = {
    DirectionLabel.PROMISING: "#2a6f4e",
    DirectionLabel.UNCERTAIN: "#c4a35a",
    DirectionLabel.INSUFFICIENT: "#888888",
    DirectionLabel.NOT_PROMISING: "#b84c4c",
}


def plot_direction_ranking(
    ranking: list[DirectionScore],
    *,
    disease_name: str,
    outfile: Path | None = None,
) -> Path:
    figures = settings()["figures_dir"]
    figures.mkdir(parents=True, exist_ok=True)
    path = outfile or figures / f"ranking_{ranking[0].disease_id if ranking else 'na'}.png"

    labels = [r.direction_name for r in ranking][::-1]
    scores = [r.score for r in ranking][::-1]
    colors = [_COLORS.get(r.label, "#8c3a3a") for r in ranking[::-1]]

    fig, ax = plt.subplots(figsize=(10, max(3.5, 0.55 * max(len(labels), 1) + 1.5)))
    ax.barh(labels, scores, color=colors)
    ax.set_xlim(0, 100)
    ax.set_xlabel("Prospect score (0–100), conservative")
    ax.set_title(f"Mito directions vs evidence — {disease_name}")
    for i, (s, r) in enumerate(zip(scores, ranking[::-1])):
        ax.text(
            min(max(s, 1) + 1.5, 88),
            i,
            f"{s:.0f} | {r.label.value} | {r.evidence_level_best.value}",
            va="center",
            fontsize=8,
        )
    ax.axvline(65, color="#2a6f4e", lw=0.8, ls="--", alpha=0.7)
    ax.axvline(40, color="#888", lw=0.8, ls=":")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path
