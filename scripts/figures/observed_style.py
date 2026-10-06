"""Shared style for the per-model observed-run figures (copied from paper figuregen/observed_style.py;
only change: export() takes an explicit output directory).

Categorical slots follow a validated order (blue, orange, aqua, violet):
adjacent CVD dE >= 9.2, normal-vision dE >= 27.6 on a white surface.
Aqua sits below 3:1 contrast, so every aqua mark carries a direct label.
"""
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
WIDTH = 473.0
INK, MUTED, FAINT = "#15243B", "#58677E", "#9AA5B1"
GRID, FRAME = "#E8EDF3", "#D5DCE5"
BLUE, ORANGE, AQUA, VIOLET = "#2A78D6", "#EB6834", "#1BAF7A", "#4A3AA7"
# Ordinal blue ramp for 0-3 ratings (validated monotone, single hue).
RAMP = ["#C9CED6", "#86B6EF", "#3987E5", "#1C5CAB", "#0D366B"]


def configure():
    plt.rcParams.update({
        "font.family": "Liberation Sans", "font.size": 7.8,
        "axes.labelsize": 7.8, "axes.labelcolor": MUTED,
        "xtick.labelsize": 7.4, "ytick.labelsize": 7.6,
        "xtick.color": MUTED, "ytick.color": MUTED,
        "text.color": INK, "pdf.fonttype": 42, "svg.fonttype": "none",
        "svg.hashsalt": "cowork-observed",
    })


def figure(height):
    return plt.figure(figsize=(WIDTH / 72, height / 72), facecolor="white")


def axes(fig, x, y, w, h):
    H = fig.get_figheight() * 72
    return fig.add_axes((x / WIDTH, y / H, w / WIDTH, h / H))


def text(fig, x, y, s, **kw):
    H = fig.get_figheight() * 72
    kw.setdefault("color", INK)
    return fig.text(x / WIDTH, y / H, s, **kw)


def header(fig, x, y, letter, title, subtitle=None):
    text(fig, x, y, f"({letter})", size=8.8, weight="bold", color=BLUE)
    text(fig, x + 17, y, title, size=8.8, weight="bold")
    if subtitle:
        text(fig, x + 17, y - 11.5, subtitle, size=7.4, color=MUTED)


def clean(ax, grid="y"):
    ax.set_axisbelow(True)
    if grid:
        ax.grid(axis=grid, color=GRID, linewidth=0.6)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(FRAME)
    ax.spines["bottom"].set_linewidth(0.7)
    ax.tick_params(length=0, pad=3.5)


def export(fig, stem, title, outdir=None):
    out = Path(outdir or (ROOT / "figures")) / stem
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out.with_suffix(".pdf"), metadata={
        "Title": title, "Creator": "figuregen", "CreationDate": None, "ModDate": None})
    fig.savefig(out.with_suffix(".svg"), metadata={"Date": None})
    svg = out.with_suffix(".svg")
    svg.write_text(re.sub(r"[ \t]+$", "", svg.read_text(encoding="utf-8"), flags=re.MULTILINE),
                   encoding="utf-8")
    fig.savefig(out.with_suffix(".png"), dpi=216)
    plt.close(fig)
