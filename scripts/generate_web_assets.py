"""Generate the raster assets the web interface needs.

    python3 scripts/generate_web_assets.py

Kept as a script so the favicons and the social preview image are reproducible
from source rather than being binaries of unknown origin sitting in the tree.
Everything is drawn with the same palette as the stylesheet.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

OUT = Path("web/static/img")
PAPER = "#EFE6D0"
SOIL = "#33291D"
WHEAT = "#D8C79F"
CLAY = "#A35A32"
OLIVE = "#4C5A3A"


def _mark(ax) -> None:
    """The logo: a guidance line, an implement track, and the tractor on it."""
    ax.add_patch(Rectangle((0, 0), 40, 40, color=SOIL))
    ax.plot([4, 36], [26, 26], color=WHEAT, lw=3.4, solid_capstyle="butt")
    ax.plot([4, 14, 22, 36], [15, 15, 12, 11.5], color=CLAY, lw=3.4)
    ax.plot([12], [26], marker="o", ms=6.5, color="#8FA06B")
    ax.set_xlim(0, 40)
    ax.set_ylim(0, 40)
    ax.axis("off")


def icon(size: int, name: str) -> None:
    fig = plt.figure(figsize=(size / 100, size / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    _mark(ax)
    fig.savefig(OUT / name, dpi=100, facecolor=SOIL)
    plt.close(fig)


def og_image() -> None:
    """1200 x 630 social preview. Alt text lives in the template."""
    fig = plt.figure(figsize=(12, 6.3), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.add_patch(Rectangle((0, 0), 1200, 630, color=PAPER))

    for y in range(60, 630, 70):
        ax.plot([0, 1200], [y, y], color="#DCCFB0", lw=1)

    ax.plot([70, 1130], [300, 300], color=SOIL, lw=3, dashes=(9, 7))
    ax.plot([70, 330, 620, 1000], [200, 200, 292, 296], color=OLIVE, lw=7)
    ax.plot([70, 380, 700, 1000], [140, 140, 232, 238], color=CLAY, lw=7)

    ax.text(70, 470, "The tractor is on the line.", fontsize=46,
            family="serif", color=SOIL, weight="bold")
    ax.text(70, 405, "The implement is not.", fontsize=46,
            family="serif", color=CLAY, weight="bold")
    ax.text(70, 90, "Implement-Aware Guidance Simulator", fontsize=21,
            family="monospace", color="#6B5B44")

    ax.text(1020, 289, "tractor", fontsize=18, family="serif", color=OLIVE, ha="left", va="center")
    ax.text(1020, 231, "implement", fontsize=18, family="serif", color=CLAY, ha="left", va="center")
    ax.text(1020, 208, "edge", fontsize=18, family="serif", color=CLAY, ha="left", va="center")

    ax.set_xlim(0, 1200)
    ax.set_ylim(0, 630)
    ax.axis("off")
    fig.savefig(OUT / "og-image.png", dpi=100, facecolor=PAPER)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    icon(32, "favicon-32.png")
    icon(180, "apple-touch-icon.png")
    icon(512, "icon-512.png")
    og_image()
    for f in sorted(OUT.iterdir()):
        print(f"  {f.name:24s} {f.stat().st_size / 1024:7.1f} kB")


if __name__ == "__main__":
    main()
