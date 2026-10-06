#!/usr/bin/env python3
"""Per-model versions of the four observed-run paper figures.

Visual design and data definitions follow paper/figuregen/{fig_requirement_flow,fig_observed_effort,
fig_observed_behaviour,fig_workplace_basics}.py; hard-coded Opus-5.5 counts, titles and axis limits are
replaced by values from OUT/statistics.json and OUT/data/*.csv.  Writes OUT/figures/*.{pdf,svg,png}.

    python3 scripts/figures/model_figures.py --out OUT [--model NAME]
"""
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

import matplotlib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import config  # noqa: E402
from observed_style import (AQUA, BLUE, FAINT, FRAME, INK, MUTED, ORANGE, VIOLET, axes, clean,  # noqa: E402
                            configure, export, figure, header, text)

LABELS = {
    "search_strategy": "Search strategy", "decomposition_prioritization": "Decomposition & priority",
    "hypothesis_testing": "Hypothesis testing", "information_value": "Information value",
    "abstraction_transfer": "Abstraction & transfer", "causal_debugging": "Causal debugging",
    "feedback_adaptation": "Feedback adaptation", "information_integration": "Information integration",
    "verification_design": "Verification design", "calibration_stopping": "Calibration & stopping",
    "scope_reconstruction": "Scope reconstruction", "provenance_version_reconciliation": "Provenance & versions",
    "owner_question_followthrough": "Owner questions", "notification_handling": "Notification handling",
    "evidence_to_implementation": "Evidence to code", "delivery_accountability": "Delivery accountability",
}
COLORS = {0: "#C2543D", 1: "#9EC5F4", 2: "#3987E5", 3: "#104281"}


def nice_max(v, steps=(1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10)):
    if v <= 0:
        return 1
    e = 10 ** math.floor(math.log10(v))
    for s in steps:
        if s * e >= v:
            return s * e
    return 10 * e


def load(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def rect(fig, x, y, w, h, H, color):
    fig.patches.append(matplotlib.patches.Rectangle((x / 473, y / H), w / 473, h / H, transform=fig.transFigure,
                                                    facecolor=color, edgecolor="none"))


def fig_requirement_flow(cfg, s, outdir):
    req, loss = s["requirements"], s["loss"]
    acq = Counter(req["acquisition"])
    total = req["colleague_held"]
    obtained = acq["obtained"] + acq["returned_not_visible"]
    asked_card = acq["asked_owner_about_card"] + acq["asked_wrong_person_about_card"]
    owner_only, never = acq["contacted_owner_not_card"], acq["owner_never_contacted"]
    fig = figure(300)
    header(fig, 6, 282, "a", "Colleague-held requirements",
           f"{total:,} requirements held by a named colleague, {req['tasks']} tasks")
    ax = axes(fig, 6, 230, 461, 22)
    parts = [("Disclosed to the agent", obtained, BLUE), ("Owner asked about the card", asked_card, ORANGE),
             ("Owner asked, card not raised", owner_only, VIOLET), ("Owner never contacted", never, "#9AA5B1")]
    left = 0
    for name, value, color in parts:
        ax.barh(0, value, left=left, height=1, color=color, edgecolor="white", linewidth=1.6)
        share = 100 * value / total if total else 0
        if share > 6:
            ax.text(left + value / 2, 0, f"{share:.0f}%", ha="center", va="center", color="white", size=8.2, weight="bold")
        left += value
    ax.set_xlim(0, max(total, 1))
    ax.set_ylim(-0.5, 0.5)
    ax.axis("off")
    x = 6
    for name, value, color in parts:
        rect(fig, x, 207, 7, 7, 300, color)
        text(fig, x + 10, 208, name, size=7.3, va="bottom")
        text(fig, x + 10, 197, f"{value:,} ({100 * value / total if total else 0:.0f}%)", size=7.0, color=MUTED, va="bottom")
        x += 121 if name.startswith("Disclosed") else 118
    header(fig, 6, 164, "b", "Pass rate by what the agent received", "F2P nodes, by the state of the requirement they test")
    groups = [("Public record", "public"), ("Colleague-held, disclosed", "colleague_obtained"),
              ("Colleague-held, not disclosed", "colleague_not_obtained")]
    bx = axes(fig, 118, 22, 104, 112)
    nps = s["node_pass_by_state"]
    vals = [nps.get(k, {}).get("pass_pct") or 0 for _, k in groups]
    ns = [nps.get(k, {}).get("n", 0) for _, k in groups]
    y = np.arange(len(groups))
    bx.barh(y, vals, height=0.58, color=["#9AA5B1", BLUE, ORANGE], zorder=3)
    bx.set_ylim(len(groups) - 0.45, -0.55)
    bx.set_xlim(0, 100)
    bx.set_yticks([])
    bx.set_xticks([0, 50, 100])
    bx.set_xlabel("Nodes passed (%)", labelpad=4)
    clean(bx, "x")
    for yi, v, n, (name, _) in zip(y, vals, ns, groups):
        bx.text(v + 3, yi, f"{v:.0f}", va="center", size=8, weight="bold", color=INK)
        bx.text(-5, yi - 0.13, name, va="center", ha="right", size=7.3, color=INK)
        bx.text(-5, yi + 0.22, f"{n:,} nodes", va="center", ha="right", size=6.8, color=MUTED)
    na = loss["attributed"]
    st_ = loss["stages"]
    ask_raised = loss["ask_detail"].get("card_raised", 0)
    header(fig, 252, 164, "c", "Where failed nodes were lost", f"Earliest stage, {na} failed F2P nodes")
    cx = axes(fig, 302, 22, 120, 112)
    order = [("Discovery", "discovery"), ("Ask", "ask"), ("Read", "read"), ("Implement", "implement")]
    v = [st_.get(k, 0) for _, k in order]
    xmax = nice_max(max(v + [1]) * 1.05)
    cx.barh(0, v[0], height=0.58, color="#9AA5B1", zorder=3)
    cx.barh(1, ask_raised, height=0.58, color=ORANGE, zorder=3)
    cx.barh(1, v[1] - ask_raised, left=ask_raised, height=0.58, color=VIOLET, zorder=3, edgecolor="white", linewidth=1.2)
    cx.barh(2, v[2], height=0.58, color=AQUA, zorder=3)
    cx.barh(3, v[3], height=0.58, color=BLUE, zorder=3)
    cx.set_ylim(len(order) - 0.45, -0.55)
    cx.set_xlim(0, xmax)
    cx.set_yticks(np.arange(4), [n for n, _ in order], size=7.6, color=INK)
    cx.set_xticks([0, xmax / 2, xmax])
    cx.set_xlabel("Failed F2P nodes", labelpad=4)
    clean(cx, "x")
    for yi, value in enumerate(v):
        cx.text(value + xmax * 0.024, yi, f"{value} ({100 * value / na if na else 0:.0f}%)", va="center", size=7.6, color=INK)
    if ask_raised > xmax * 0.18:
        cx.text(ask_raised / 2, 1, "raised", ha="center", va="center", size=6.6, color="white")
    if v[1] - ask_raised > xmax * 0.22:
        cx.text(ask_raised + (v[1] - ask_raised) / 2, 1, "not raised", ha="center", va="center", size=6.6, color="white")
    export(fig, "fig_requirement_flow", f"SWE-CoWork: requirement acquisition and loss ({cfg.model})", outdir)


def fig_effort(cfg, s, outdir):
    runs = load(cfg.data / "runs.csv")
    stop_p = cfg.data / "stopping.csv"
    stop = {r["row"]: r for r in load(stop_p)} if stop_p.exists() and s.get("stopping") else {}
    f2p = np.array([100 * float(r["f2p_rate"]) for r in runs])
    flagged = np.array([r["preexisting_quality_flag"] == "True" for r in runs])
    fig = figure(312)
    panels = [("tool_calls", "Tool calls", "a", 6, 172), ("chat_send_attempts", "Colleague messages", "b", 166, 172),
              ("agent_wall_hours", "Wall-clock hours", "c", 326, 172)]
    for key, title, letter, x0, y0 in panels:
        x = np.array([float(r[key]) for r in runs])
        rho = s["effort_vs_f2p"].get(key, {}).get("spearman")
        header(fig, x0, 294, letter, title, f"Spearman ρ = {rho:+.2f}" if rho is not None else "Spearman ρ n/a")
        ax = axes(fig, x0 + 22, y0, 118, 88)
        ax.scatter(x[~flagged], f2p[~flagged], s=12, color=BLUE, alpha=0.7, edgecolors="white", linewidths=0.35, zorder=3)
        ax.scatter(x[flagged], f2p[flagged], s=16, marker="D", color=ORANGE, edgecolors="white", linewidths=0.35, zorder=4)
        med = np.median(x)
        ax.axvline(med, color=FAINT, linewidth=0.8, linestyle=(0, (2, 2)), zorder=1)
        ax.text(med, 108, f"median {med:.0f}" if key != "agent_wall_hours" else f"median {med:.1f} h", ha="center", size=6.5, color=MUTED)
        ax.set_ylim(-4, 104)
        ax.set_yticks([0, 50, 100])
        ax.set_xlim(left=0, right=8.2 if key == "agent_wall_hours" else None)
        if key == "agent_wall_hours":
            ax.set_xticks([0, 2, 4, 6, 8])
        clean(ax, "y")
        if letter == "a":
            ax.set_ylabel("F2P (%)", labelpad=2)
    if flagged.any():
        fig.add_artist(matplotlib.lines.Line2D([350 / 473], [150.5 / 312], marker="D", color=ORANGE, markersize=3.6,
                                               transform=fig.transFigure, linestyle=""))
        text(fig, 356, 148, f"pre-existing quality flag ({int(flagged.sum())} runs)", size=6.6, color=MUTED)
    o = s["outcomes"]
    header(fig, 6, 128, "d", "Per-run F2P resolution",
           f"Mean {o['selected']['macro_f2p_percent']:.1f}% · median {o['median_f2p_percent']:.0f}% · {o['selected']['strict_count']} strict")
    hx = axes(fig, 28, 34, 186, 62)
    bins = np.arange(0, 101, 10)
    counts, _, patches = hx.hist(np.clip(f2p, 0, 99.999), bins=bins, color=BLUE, edgecolor="white", linewidth=1.2, zorder=3)
    patches[-1].set_facecolor("#104281")
    for xx, c in zip(bins[:-1], counts):
        hx.text(xx + 5, c + 0.6, f"{int(c)}", ha="center", va="bottom", size=6.6, color=MUTED)
    hx.set_xlim(0, 100)
    hx.set_xticks([0, 25, 50, 75, 100])
    ymax = max(counts.max() * 1.25, 1)
    hx.set_ylim(0, ymax)
    hx.set_yticks([t for t in (0, 10, 20, 30, 40) if t <= ymax])
    hx.set_xlabel("F2P (%)", labelpad=3)
    hx.set_ylabel("Runs", labelpad=2)
    clean(hx, "y")
    header(fig, 252, 128, "e", "How runs ended", "Reviewer judgement: did the agent stop early?")
    if stop:
        bx = axes(fig, 330, 34, 100, 62)
        cats = [("Early stop", "supported", ORANGE), ("Uncertain", "uncertain", VIOLET),
                ("Not supported", "not_supported", BLUE), ("Time budget", "time", FAINT)]
        cnt = []
        for _, k, _ in cats:
            if k == "time":
                cnt.append(sum(v["ending_type"] == "time_budget" for v in stop.values()))
            else:
                cnt.append(sum(v["premature_stop"] == k and v["ending_type"] != "time_budget" for v in stop.values()))
        y = np.arange(len(cats))
        bx.barh(y, cnt, height=0.62, color=[c for *_, c in cats], zorder=3)
        bx.set_ylim(len(cats) - 0.45, -0.55)
        xm = nice_max(max(cnt) * 1.15)
        bx.set_xlim(0, xm)
        bx.set_yticks([])
        bx.set_xticks([0, xm / 2, xm])
        clean(bx, "x")
        for yi, (name, k, _), c in zip(y, cats, cnt):
            bx.text(-xm * 0.05, yi, name, ha="right", va="center", size=7, color=INK, linespacing=1.05)
            bx.text(c + xm * 0.025, yi, str(c), va="center", size=7.6, color=INK, weight="bold")
        h = s["stopping"]["supported_remaining_hours_median"]
        if h is not None:
            text(fig, 252, 12, f"Supported early stops left a median {h:.1f} h of budget.", size=6.8, color=MUTED)
    else:
        text(fig, 300, 70, "Rubric review not merged:\nno stop judgements", size=7.4, color=MUTED, linespacing=1.4)
    export(fig, "fig_observed_effort", f"SWE-CoWork: observed effort and stopping ({cfg.model})", outdir)


def fig_behaviour(cfg, s, outdir):
    if not s.get("review", {}).get("available"):
        return False
    dims_s = s["dimensions"]
    nr = s["review"]["validated_runs"]
    dims = list(LABELS)
    n = len(dims)
    fig = figure(318)
    header(fig, 6, 304, "a", "Rating distribution", f"Runs per anchored rating (0–3), {nr} runs")
    header(fig, 330, 304, "b", "Association with F2P", "Spearman ρ, 95% bootstrap CI")
    ax = axes(fig, 132, 26, 186, 238)
    cx = axes(fig, 340, 26, 124, 238)
    y = np.arange(n) + np.where(np.arange(n) >= 10, 0.6, 0)
    for yi, d in zip(y, dims):
        ds = dims_s[d]
        counts = [ds["scores"][str(k)] for k in range(4)]
        left = 0
        for k, c in enumerate(counts):
            if c:
                ax.barh(yi, c, left=left, height=0.72, color=COLORS[k], edgecolor="white", linewidth=0.8)
                if c >= 0.09 * nr:
                    ax.text(left + c / 2, yi, str(c), ha="center", va="center", size=6.6, color="white" if k >= 2 else INK)
            left += c
        if ds["unrated_n"]:
            ax.barh(yi, ds["unrated_n"], left=left, height=0.72, color="#E4E8EE", edgecolor="white", linewidth=0.8)
        ax.text(-3 * nr / 99, yi, LABELS[d], ha="right", va="center", size=7.3, color=INK)
        lo, hi = ds["ci95"]
        rho = ds["spearman"]
        if rho is None or lo is None:
            continue
        sig = ds["ci_excludes_zero"]
        color = BLUE if sig else FAINT
        cx.plot([lo, hi], [yi, yi], color=color, linewidth=1.6, solid_capstyle="round")
        cx.plot(rho, yi, "o", color=color, markersize=4.2, markeredgecolor="white", markeredgewidth=0.6)
        cx.text(0.84, yi, f"{rho:+.2f}", ha="right", va="center", size=6.9, color=INK if sig else MUTED,
                weight="bold" if sig else "normal")
    for a in (ax, cx):
        a.set_ylim(y[-1] + 0.6, -0.6)
        a.set_yticks([])
    ax.set_xlim(0, nr)
    ax.set_xticks([0, round(nr / 4), round(nr / 2), round(3 * nr / 4), nr])
    ax.set_xlabel("Runs", labelpad=3)
    clean(ax, "x")
    cx.set_xlim(-0.45, 0.86)
    cx.set_xticks([-0.25, 0, 0.25, 0.5])
    cx.axvline(0, color=FRAME, linewidth=0.8, zorder=0)
    cx.set_xlabel("ρ with F2P", labelpad=3)
    clean(cx, "x")

    def ypt(v):
        return 26 + 238 * (y[-1] + 0.6 - v) / (y[-1] + 1.2)
    text(fig, 6, ypt(y[0]) + 8, "STRATEGY", size=6.4, color=MUTED, weight="bold")
    text(fig, 6, ypt(y[10]) + 8, "COLLABORATION", size=6.4, color=MUTED, weight="bold")
    lx = 196
    text(fig, lx - 4, 277, "Rating", size=7, color=MUTED, ha="right")
    for k, name in enumerate(["0", "1", "2", "3", "Unrated"]):
        rect(fig, lx, 276.5, 7, 7, 318, COLORS.get(k, "#E4E8EE"))
        text(fig, lx + 10, 277, name, size=7, color=INK)
        lx += 24
    export(fig, "fig_observed_behaviour", f"SWE-CoWork: observed behaviour profile ({cfg.model})", outdir)
    return True


def fig_workplace(cfg, s, outdir):
    dc, df = s["delivery_claims"], s["deferrals"]
    fig = figure(236)
    header(fig, 6, 218, "a", "What the handoff said", f"{dc['scored']:,} requirements with tests, by test outcome")
    ax = axes(fig, 70, 60, 150, 104)
    t = dc["table"]
    cls = [("Reported done", "claimed_done", ORANGE), ("Flagged open", "claimed_partial_or_open", VIOLET),
           ("Not mentioned", "not_mentioned", FAINT)]
    for yi, (lab, d) in enumerate([("Tests fail", "False"), ("Tests pass", "True")]):
        n = sum(t.get(f"{k}|{d}", 0) for _, k, _ in cls)
        left = 0
        for name, k, c in cls:
            v = 100 * t.get(f"{k}|{d}", 0) / n if n else 0
            ax.barh(yi, v, left=left, height=0.62, color=c, edgecolor="white", linewidth=1.4)
            if v >= 6:
                ax.text(left + v / 2, yi, f"{v:.0f}%", ha="center", va="center", size=7.6, color="white", weight="bold")
            left += v
        ax.text(-4, yi - 0.1, lab, ha="right", va="center", size=7.5, color=INK)
        ax.text(-4, yi + 0.24, f"{n:,} reqs", ha="right", va="center", size=6.7, color=MUTED)
    ax.set_xlim(0, 100)
    ax.set_ylim(1.5, -0.5)
    ax.set_yticks([])
    ax.set_xticks([0, 50, 100])
    ax.set_xlabel("Share of requirements (%)", labelpad=3)
    clean(ax, None)
    x0 = 6
    for name, _, c in cls:
        rect(fig, x0, 177, 7, 7, 236, c)
        text(fig, x0 + 10, 177.5, name, size=7, color=INK)
        x0 += 74
    if dc["claimed_done"]:
        text(fig, 6, 14, f"{dc['claimed_done_failed_pct']:.0f}% of the {dc['claimed_done']:,} requirements reported as done "
             "fail their tests.", size=7, color=MUTED)
    header(fig, 248, 218, "b", "After a colleague says “later”", f"{df['threads']} threads where the owner first deferred")
    bx = axes(fig, 330, 150, 92, 36)
    groups = [("Asked again", df["followed"], df["followed_disclosed"]),
              ("Never asked again", df["abandoned"], df["abandoned_disclosed"])]
    xm = nice_max(max(df["followed"], df["abandoned"], 1) * 1.0)
    for yi, (name, n, d) in enumerate(groups):
        bx.barh(yi, n, height=0.62, color=FAINT, zorder=2)
        bx.barh(yi, d, height=0.62, color=BLUE, zorder=3)
        bx.text(-xm * 0.017, yi, f"{name} ({n})", ha="right", va="center", size=7.2, color=INK)
        bx.text(n + xm * 0.02, yi, f"{100 * d / n:.0f}%" if n else "–", va="center", size=7.6, color=INK, weight="bold")
    bx.set_xlim(0, xm)
    bx.set_ylim(1.5, -0.5)
    bx.set_yticks([])
    bx.set_xticks([])
    for sp in bx.spines.values():
        sp.set_visible(False)
    text(fig, 330, 138, "blue: requirement eventually disclosed", size=6.7, color=MUTED)
    qt = s["question_timing"]
    header(fig, 248, 112, "c", "When questions are sent", f"Share of {qt['total']:,} messages, by tenth of the run")
    cx = axes(fig, 262, 26, 200, 52)
    dec = np.array(qt["deciles"], dtype=float)
    share = 100 * dec / dec.sum() if dec.sum() else dec
    cx.bar(np.arange(10), share, width=0.8, color=VIOLET, zorder=3)
    cx.set_xticks([0, 9], ["first", "last"])
    cx.set_xlim(-0.6, 9.6)
    top = nice_max(max(share.max() * 1.05, 1))
    cx.set_yticks([0, top / 2, top])
    cx.set_ylim(0, top)
    cx.set_ylabel("%", labelpad=2)
    clean(cx, "y")
    export(fig, "fig_workplace_basics", f"SWE-CoWork: workplace basics ({cfg.model})", outdir)


def main():
    cfg = config()
    s = json.loads((cfg.out / "statistics.json").read_text())
    outdir = cfg.out / "figures"
    configure()
    made = ["fig_requirement_flow", "fig_observed_effort", "fig_workplace_basics"]
    fig_requirement_flow(cfg, s, outdir)
    fig_effort(cfg, s, outdir)
    fig_workplace(cfg, s, outdir)
    if fig_behaviour(cfg, s, outdir):
        made.append("fig_observed_behaviour")
    print(json.dumps({"figures": [str(outdir / (m + ".pdf")) for m in made]}))


if __name__ == "__main__":
    main()
