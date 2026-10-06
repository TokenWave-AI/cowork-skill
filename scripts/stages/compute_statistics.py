#!/usr/bin/env python3
"""statistics.json for one model: every number the report, LaTeX rows and figures use.

Merges (definitions unchanged):
  * analysis/observed_statistics.py      outcomes, sensitivity cohort, effort quantiles, rubric counts
  * analysis/observed_extended_statistics.py  requirement acquisition, node pass by state, paired gap,
                                         loss attribution, collaboration metrics + Spearman, rubric vs F2P,
                                         effort vs F2P, stopping, delivery claims, deferrals, question
                                         timing, rule compliance, strata
plus the extra sentences of content/6_Results.tex (per-run F2P distribution, P2P preservation,
loss-stage share by stop label, ...), bootstrap CIs for the rubric correlations (same RNG procedure
as figuregen/fig_observed_behaviour.py), data-coverage notes and three auto-selected case candidates.

Inputs: OUT/data/*.csv (stages nodes..basics), optional OUT/review/summary/RUN_ANALYSIS.csv and
OUT/data/stopping.csv (review stage), package release101_tasks.json (strata), optional
--claims-blind-check CSV (row,card_id,verdict,quote).
"""
import collections
import csv
import json
import math
import statistics as st
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr, wilcoxon

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import config, read_csv  # noqa: E402

DIMENSIONS = {
    "search_strategy": "Search strategy", "decomposition_prioritization": "Decomposition/prioritization",
    "hypothesis_testing": "Hypothesis testing", "information_value": "Information value",
    "abstraction_transfer": "Abstraction/transfer", "causal_debugging": "Causal debugging",
    "feedback_adaptation": "Feedback adaptation", "information_integration": "Information integration",
    "verification_design": "Verification design", "calibration_stopping": "Calibration/stopping",
    "scope_reconstruction": "Scope reconstruction",
    "provenance_version_reconciliation": "Provenance/version reconciliation",
    "owner_question_followthrough": "Owner questions/follow-through",
    "notification_handling": "Notification handling", "evidence_to_implementation": "Evidence to implementation",
    "delivery_accountability": "Delivery accountability",
}
STAGES = ("discovery", "ask", "read", "implement")


def pct(x):
    return 100 * x


def percentile(values, fraction):
    values = sorted(values)
    index = (len(values) - 1) * fraction
    lo, hi = math.floor(index), math.ceil(index)
    return values[lo] + (index - lo) * (values[hi] - values[lo])


def mean_or_none(v):
    v = list(v)
    return st.mean(v) if v else None


def median_or_none(v):
    v = list(v)
    return st.median(v) if v else None


def sp(a, b):
    if len(a) < 3 or len(set(a)) < 2 or len(set(b)) < 2:
        return None, None
    r = spearmanr(a, b)
    return float(r.statistic), float(r.pvalue)


def outcome(rows):
    if not rows:
        return None
    strict = sum(all(int(r[g + "_passed"]) == int(r[g + "_total"]) for g in ("f2p", "p2p")) for r in rows)
    return {"n": len(rows), "macro_f2p_percent": st.mean(float(r["f2p_rate"]) for r in rows) * 100,
            "macro_p2p_percent": st.mean(float(r["p2p_rate"]) for r in rows) * 100,
            "strict_count": strict, "strict_percent": strict / len(rows) * 100}


def main():
    cfg = config(extra_args=lambda p: p.add_argument("--claims-blind-check", default=None))
    D = cfg.data
    runs_l = read_csv(D / "runs.csv")
    runs = {r["row"]: r for r in runs_l}
    out = {"schema": "cowork-model-report-statistics-v1", "model": cfg.model,
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "sources": {"campaign": str(cfg.campaign), "bundle": str(cfg.bundle), "package": str(cfg.package)}}
    f2p = {k: float(r["f2p_rate"]) for k, r in runs.items()}
    strict = {k: r["f2p_passed"] == r["f2p_total"] and r["p2p_passed"] == r["p2p_total"] for k, r in runs.items()}

    # ---------------------------------------------------------------- outcomes and effort
    clean = [r for r in runs_l if r["preexisting_quality_flag"] == "False"]
    fv = list(f2p.values())
    out["outcomes"] = {
        "selected": outcome(runs_l), "sensitivity": outcome(clean),
        "preexisting_quality_flag_rows": [r["row"] for r in runs_l if r["preexisting_quality_flag"] == "True"],
        "median_f2p_percent": pct(st.median(fv)), "runs_f2p_ge_90": sum(x >= .9 for x in fv),
        "runs_f2p_lt_25": sum(x < .25 for x in fv),
        "runs_p2p_all_preserved": sum(r["p2p_passed"] == r["p2p_total"] for r in runs_l),
        "f2p_histogram_10": [sum(1 for x in fv if b <= min(x * 100, 99.999) < b + 10) for b in range(0, 100, 10)]}
    effort = {}
    for field in ["tool_calls", "chat_send_attempts", "distinct_colleague_recipients_attempted", "agent_wall_hours"]:
        values = [float(r[field]) for r in runs_l if r[field] != ""]
        effort[field] = {"n": len(values), "median": st.median(values),
                         "p25": percentile(values, .25), "p75": percentile(values, .75)}
    out["effort"] = effort
    out["cost"] = {"tokens_k_median": None, "tokens_note": "exact cumulative solver tokens not recorded",
                   "wall_clock_minutes_median": effort["agent_wall_hours"]["median"] * 60,
                   "tool_calls_median": effort["tool_calls"]["median"]}
    out["effort_vs_f2p"] = {}
    for k in ("tool_calls", "chat_send_attempts", "agent_wall_hours"):
        rho, p = sp([float(runs[r][k]) for r in runs], [f2p[r] for r in runs])
        out["effort_vs_f2p"][k] = dict(spearman=rho, p=p)

    # ---------------------------------------------------------------- requirement level
    reqs = read_csv(D / "requirements.csv")
    all_nodes = read_csv(D / "f2p_nodes.csv")
    nodes = [n for n in all_nodes if n["status"] in ("passed", "failed")]
    collab = {r["row"]: r for r in read_csv(D / "collaboration_runs.csv")}
    held = [r for r in reqs if r["holder"] == "colleague"]
    acq = collections.Counter(r["acquisition"] for r in held)
    n_held = len(held)
    share = lambda *ks: pct(sum(acq[k] for k in ks) / n_held) if n_held else None
    out["requirements"] = dict(total=len(reqs), colleague_held=n_held, public=len(reqs) - n_held,
                               acquisition=dict(acq), tasks=len({r["row"] for r in held}),
                               shares_pct=dict(obtained=share("obtained", "returned_not_visible"),
                                               obtained_visible=share("obtained"),
                                               card_raised_not_disclosed=share("asked_owner_about_card", "asked_wrong_person_about_card"),
                                               owner_contacted_card_not_raised=share("contacted_owner_not_card"),
                                               owner_never_contacted=share("owner_never_contacted")))
    by_state = collections.defaultdict(list)
    per_task = collections.defaultdict(lambda: collections.defaultdict(list))
    for n in nodes:
        by_state[n["information_state"]].append(n["status"] == "passed")
        per_task[n["row"]][n["information_state"]].append(n["status"] == "passed")
    out["node_pass_by_state"] = {k: dict(n=len(v), pass_pct=pct(st.mean(v))) for k, v in by_state.items()}
    diffs = [st.mean(v["colleague_obtained"]) - st.mean(v["colleague_not_obtained"])
             for v in per_task.values() if v["colleague_obtained"] and v["colleague_not_obtained"]]
    out["paired_disclosure_gap"] = dict(
        tasks=len(diffs), mean_pp=pct(st.mean(diffs)) if diffs else None,
        median_pp=pct(st.median(diffs)) if diffs else None,
        positive=sum(d > 0 for d in diffs), negative=sum(d < 0 for d in diffs),
        wilcoxon_p=float(wilcoxon(diffs).pvalue) if len([d for d in diffs if d]) >= 2 else None)
    hi = [n for n in nodes if n["mapping_confidence"] == "high"]
    out["node_pass_by_state_high_conf"] = {
        k: dict(n=len(v), pass_pct=pct(st.mean(v)) if v else None) for k, v in
        ((k, [n["status"] == "passed" for n in hi if n["information_state"] == k])
         for k in ("public", "colleague_obtained", "colleague_not_obtained"))}
    out["mapping_confidence"] = dict(collections.Counter(n["mapping_confidence"] for n in nodes))
    out["mapping_confidence_all_nodes"] = dict(collections.Counter(n["mapping_confidence"] for n in all_nodes))
    out["f2p_nodes"] = dict(total=len(all_nodes), graded=len(nodes),
                            unresolved=sum(n["status"] == "unresolved" for n in all_nodes),
                            unresolved_rows=sorted({n["row"] for n in all_nodes if n["status"] == "unresolved"}))

    # ---------------------------------------------------------------- loss attribution
    failed = [n for n in all_nodes if n["status"] == "failed"]
    stage = collections.Counter(n["loss_stage"] for n in failed)
    att = [n for n in failed if n["loss_stage"] in STAGES]
    na = len(att)
    impl_fc = collections.Counter(n["failure_class"] for n in att if n["loss_stage"] == "implement")
    out["loss"] = dict(failed=len(failed), attributed=na, stages=dict(stage),
                       shares_pct={k: (pct(stage.get(k, 0) / na) if na else None) for k in STAGES},
                       ask_detail=dict(collections.Counter(n["ask_detail"] for n in att if n["loss_stage"] == "ask")),
                       implement_failure_class=dict(impl_fc),
                       implement_build_or_load=impl_fc.get("solver_runtime_or_load_error", 0) + impl_fc.get("solver_compile_error", 0),
                       runs_with_failures=len({n["row"] for n in att}),
                       excluded_infrastructure=stage.get("excluded_infrastructure", 0),
                       unmapped=stage.get("unmapped", 0))

    # ---------------------------------------------------------------- collaboration metrics
    metrics = ["ask_rate", "targeting", "gain_per_q", "followthrough", "redundancy", "unread", "obtained_rate"]
    out["collaboration"] = {}
    for m in metrics:
        v = [(float(collab[k][m]), f2p[k]) for k in collab if collab[k][m] != "" and k in f2p]
        rho, p = sp([a for a, _ in v], [b for _, b in v])
        out["collaboration"][m] = dict(n=len(v), mean=mean_or_none(a for a, _ in v),
                                       median=median_or_none(a for a, _ in v), spearman=rho, p=p)
    rhos = [abs(out["collaboration"][m]["spearman"]) for m in metrics[:-1] if out["collaboration"][m]["spearman"] is not None]
    out["collaboration_max_abs_rho_excl_obtained"] = max(rhos) if rhos else None

    # ---------------------------------------------------------------- rubric review (optional)
    ra_path = cfg.review / "summary" / "RUN_ANALYSIS.csv"
    stop_path = D / "stopping.csv"
    review = {r["row"]: r for r in read_csv(ra_path)} if ra_path.exists() else {}
    out["review"] = dict(available=bool(review), validated_runs=len(review),
                         runs_without_review=sorted(set(runs) - set(review)))
    if review:
        dims = {}
        rng = np.random.default_rng(7)  # same procedure as figuregen/fig_observed_behaviour.py
        n_sig = 0
        for d, label in DIMENSIONS.items():
            sc = [(review[k].get(d + "_score", ""), review[k].get(d + "_status", "")) for k in sorted(review)]
            scores = collections.Counter(s for s, _ in sc if s != "")
            statuses = collections.Counter(s for _, s in sc)
            v = [(float(review[k][d + "_score"]), f2p[k]) for k in sorted(review) if review[k].get(d + "_score", "") != ""]
            rho, p = sp([a for a, _ in v], [b for _, b in v])
            by = collections.defaultdict(list)
            for s_, y in v:
                by[int(s_)].append(y)
            arr = np.array(v)
            boots = []
            for _ in range(1000):
                idx = rng.integers(0, len(arr), len(arr))
                r_ = spearmanr(arr[idx, 0], arr[idx, 1]).statistic
                if not np.isnan(r_):
                    boots.append(r_)
            lo, hi_ = (float(x) for x in np.percentile(boots, [2.5, 97.5])) if boots else (None, None)
            sig = boots and (lo > 0 or hi_ < 0)
            n_sig += bool(sig)
            rated = sum(scores.values())
            dims[d] = dict(label=label, rated_n=rated, scores={str(s): scores[str(s)] for s in range(4)},
                           unrated_n=len(review) - rated, statuses=dict(statuses), spearman=rho, p=p,
                           ci95=[lo, hi_], ci_excludes_zero=bool(sig),
                           mean_f2p_by_rating={str(s): dict(n=len(y), f2p=pct(st.mean(y))) for s, y in sorted(by.items())})
        out["dimensions"] = dims
        out["dimensions_ci_excluding_zero"] = n_sig
        ranked = sorted(((d, v["spearman"]) for d, v in dims.items() if v["ci_excludes_zero"]), key=lambda x: -x[1])
        out["dimensions_significant_ranked"] = [dict(dimension=d, label=DIMENSIONS[d], spearman=r) for d, r in ranked]
        top3 = sorted(dims.items(), key=lambda kv: -kv[1]["scores"]["3"])[:3]
        out["dimensions_top_rated3"] = [dict(dimension=d, label=v["label"], runs=v["scores"]["3"]) for d, v in top3]
        low = min(dims.items(), key=lambda kv: (sum(int(s) * c for s, c in kv[1]["scores"].items()) / kv[1]["rated_n"]) if kv[1]["rated_n"] else 9)
        out["dimensions_lowest_mean"] = dict(dimension=low[0], label=low[1]["label"], rated_n=low[1]["rated_n"],
                                             modal_rating=max(low[1]["scores"], key=lambda s: low[1]["scores"][s]),
                                             modal_count=max(low[1]["scores"].values()))
    if stop_path.exists() and review:
        stop = {r["row"]: r for r in read_csv(stop_path) if r["row"] in runs}
        cnt = collections.Counter((s["ending_type"], s["premature_stop"]) for s in stop.values())
        auto = [k for k, s in stop.items() if s["ending_type"] == "autonomous_completion"]
        sup = [k for k in auto if stop[k]["premature_stop"] == "supported"]
        loss_by = {}
        for lab in ("supported", "uncertain", "not_supported"):
            ns = [n for n in att if stop.get(n["row"], {}).get("premature_stop") == lab]
            loss_by[lab] = dict(n=len(ns), ask_pct=pct(sum(n["loss_stage"] == "ask" for n in ns) / len(ns)) if ns else None)
        hrs = lambda k: float(runs[k]["budget_seconds"] or 28800) / 3600 - float(runs[k]["agent_wall_hours"])
        out["stopping"] = dict(
            counts={f"{a}|{b}": v for (a, b), v in cnt.items()},
            autonomous=len(auto), supported=sum(s["premature_stop"] == "supported" for s in stop.values()),
            autonomous_remaining_hours_median=median_or_none(hrs(k) for k in auto),
            supported_remaining_hours_median=median_or_none(hrs(k) for k in sup),
            known_unresolved_items=sum(int(s["known_unresolved_items"]) for s in stop.values()),
            known_unresolved_median=st.median(int(s["known_unresolved_items"]) for s in stop.values()),
            f2p_by_label={lab: (pct(st.mean(f2p[k] for k in stop if stop[k]["premature_stop"] == lab))
                                if any(stop[k]["premature_stop"] == lab for k in stop) else None)
                          for lab in ("supported", "uncertain", "not_supported")},
            time_budget=sum(s["ending_type"] == "time_budget" for s in stop.values()),
            mixed=sum(s["ending_type"] == "mixed" for s in stop.values()),
            loss_ask_share_by_label=loss_by)
    else:
        out["stopping"] = None

    # ---------------------------------------------------------------- workplace basics
    req_nodes = collections.defaultdict(list)
    for n in all_nodes:
        for q in n["req_ids"].split("|"):
            req_nodes[(n["row"], q)].append(n)

    def claims_summary(name):
        claims = [r for r in read_csv(D / name) if r["delivered"] in ("True", "False")]
        table = collections.Counter((r["claim_class"], r["delivered"]) for r in claims)
        done = [r for r in claims if r["claim_class"] == "claimed_done"]
        fl = [r for r in claims if r["delivered"] == "False"]
        per_run = collections.defaultdict(lambda: [0, 0])
        for r in fl:
            per_run[r["row"]][0] += 1
            per_run[r["row"]][1] += r["claim_class"] == "claimed_done"
        shares = [b / a for a, b in per_run.values()]
        kinds = collections.Counter()
        for r in done:
            if r["delivered"] != "False":
                continue
            fc = {n["failure_class"] for n in req_nodes[(r["row"], r["req_id"])] if n["status"] == "failed"}
            if "functional_failed" in fc:
                kinds["functional"] += 1
            elif fc and fc <= {"solver_runtime_or_load_error", "solver_compile_error"}:
                kinds["build_or_load"] += 1
            else:
                kinds["other"] += 1
        d = dict(scored=len(claims), runs=len({r["row"] for r in claims}),
                 table={f"{a}|{b}": v for (a, b), v in table.items()},
                 claimed_done=len(done), claimed_done_failed=sum(r["delivered"] == "False" for r in done),
                 failed=len(fl), failed_claimed_done=sum(r["claim_class"] == "claimed_done" for r in fl),
                 failed_listed_open=sum(r["claim_class"] == "claimed_partial_or_open" for r in fl),
                 runs_with_failures=len(per_run), median_silent_share=median_or_none(shares),
                 runs_with_silent=sum(x > 0 for x in shares), runs_half_or_more=sum(x >= 0.5 for x in shares),
                 claimed_done_failed_kind=dict(kinds))
        d["failed_not_flagged_open"] = d["failed"] - d["failed_listed_open"]
        d["failed_listed_open_pct"] = pct(d["failed_listed_open"] / d["failed"]) if d["failed"] else None
        d["failed_claimed_done_pct"] = pct(d["failed_claimed_done"] / d["failed"]) if d["failed"] else None
        d["claimed_done_failed_pct"] = pct(d["claimed_done_failed"] / d["claimed_done"]) if d["claimed_done"] else None
        return d

    out["delivery_claims"] = claims_summary("delivery_claims.csv")
    out["delivery_claims_broad"] = claims_summary("delivery_claims_broad.csv")
    bc = cfg.extra.get("claims_blind_check")
    if bc and Path(bc).exists():
        v = collections.Counter(r["verdict"] for r in read_csv(bc))
        out["delivery_claims"]["blind_check"] = dict(v, n=sum(v.values()))
    else:
        out["delivery_claims"]["blind_check"] = None
    defs = read_csv(D / "deferrals.csv")
    fol = [d for d in defs if d["followed"] == "True"]
    ab = [d for d in defs if d["followed"] == "False"]
    out["deferrals"] = dict(
        threads=len(defs), abandoned=len(ab), followed=len(fol),
        abandoned_pct=pct(len(ab) / len(defs)) if defs else None,
        followed_disclosed=sum(d["disclosed"] == "True" for d in fol),
        followed_disclosed_pct=pct(sum(d["disclosed"] == "True" for d in fol) / len(fol)) if fol else None,
        abandoned_disclosed=sum(d["disclosed"] == "True" for d in ab),
        abandoned_budget_left_median=median_or_none(float(d["budget_left_hours"]) for d in ab),
        abandoned_budget_left_over_2h=sum(float(d["budget_left_hours"]) > 2 for d in ab),
        abandoned_run_continued_median=median_or_none(float(d["hours_until_run_end"]) for d in ab),
        abandoned_run_continued_over_1h=sum(float(d["hours_until_run_end"]) > 1 for d in ab),
        runs_with_threads=len({d["row"] for d in defs}), runs_with_abandoned=len({d["row"] for d in ab}))
    q = json.loads((D / "question_deciles.json").read_text())
    fe = [v for v in q["first_edit_fraction"].values() if v is not None]
    dec = q["deciles"]
    tot = q["total"] or 1
    out["question_timing"] = dict(deciles=dec, total=q["total"], first_fifth=sum(dec[:2]) / tot,
                                  last_fifth=sum(dec[8:]) / tot, after_first_edit=q["after_first_edit"] / tot,
                                  first_edit_median_fraction=median_or_none(fe), runs_with_edit=len(fe))
    wb = read_csv(D / "workplace_basics_runs.csv")
    ruled = [r for r in wb if r["test_rule"] == "True" and r["test_migration_allowed"] == "False"]
    viol = [r for r in ruled if int(r["existing_test_files_edited"]) > 0]
    told = [r for r in wb if r["told_delivery_note"] == "True"]
    tb = [r for r in wb if r["end_reason"] == "time_budget"]
    out["workplace_rules"] = dict(
        rule_runs=len(ruled), edited_existing_tests=len(viol),
        lines_removed_median=median_or_none(int(r["existing_test_lines_removed"]) for r in viol),
        deleted_test_files=sum(int(r["existing_test_files_deleted"]) for r in viol),
        edited_rows=[r["row"] for r in viol],
        told_delivery_note=len(told),
        no_delivery_note=[r["row"] for r in told if int(r["delivery_note_bytes"]) < 50],
        time_budget_runs=len(tb),
        time_budget_no_note=sum(int(r["delivery_note_bytes"]) < 50 for r in tb))

    # ---------------------------------------------------------------- strata
    release = {f"{t['row']:03d}": t for t in json.loads(cfg.release_tasks.read_text())} if cfg.release_tasks.exists() else {}
    lang = {"Python": "Python", "TypeScript": "TypeScript / JavaScript", "JavaScript": "TypeScript / JavaScript",
            "Go": "Go / Rust", "Rust": "Go / Rust", "C++": "C++ / C# / Java / Kotlin", "C#": "C++ / C# / Java / Kotlin",
            "Java": "C++ / C# / Java / Kotlin", "Kotlin": "C++ / C# / Java / Kotlin", "PHP": "PHP / Ruby", "Ruby": "PHP / Ruby"}
    top = ("Web & Frontend", "Dev Tools & Compilers", "Data & Databases", "Games & Graphics")

    def stratum(key):
        g = collections.defaultdict(list)
        for k in runs:
            if k in release:
                g[key(k)].append(k)
        return {s: dict(n=len(v), f2p=pct(st.mean(f2p[k] for k in v)), strict=sum(strict[k] for k in v),
                        obtained=pct(st.mean(float(collab[k]["obtained_rate"]) for k in v if collab.get(k, {}).get("obtained_rate", "") != ""))
                        if any(collab.get(k, {}).get("obtained_rate", "") != "" for k in v) else None)
                for s, v in g.items()}
    nn = lambda k: release[k]["n_nodes"]
    la = lambda k: release[k]["prod_added"]
    out["strata"] = dict(
        verifier_nodes=stratum(lambda k: "<28" if nn(k) < 28 else ("28-35" if nn(k) <= 35 else ">35")),
        edit_size=stratum(lambda k: "<1k" if la(k) < 1000 else ("1k-5k" if la(k) <= 5000 else ">5k")),
        language=stratum(lambda k: lang.get(release[k]["language"], "Other")),
        domain=stratum(lambda k: release[k]["domain"] if release[k]["domain"] in top else "Other"),
        runs_without_release_metadata=sorted(set(runs) - set(release)))
    out["strict_rows_by_domain"] = dict(collections.Counter(
        (release[k]["domain"] if release[k]["domain"] in top else "Other") for k in runs if strict[k] and k in release))

    # ---------------------------------------------------------------- coverage / reconciliation
    rec = read_csv(D / "RECONCILE.csv")
    cov = json.loads((cfg.comm / "summary.json").read_text()) if (cfg.comm / "summary.json").exists() else {}
    disc = read_csv(cfg.comm / "FACT_DISCLOSURES.csv") if (cfg.comm / "FACT_DISCLOSURES.csv").exists() else []
    notif = cov.get("totals", {}).get("unique_visible_notifications")
    out["coverage"] = dict(
        runs=len(runs), reconciled=sum(r["match"] == "True" for r in rec),
        unreconciled=[dict(row=r["row"], notes=r["notes"]) for r in rec if r["match"] != "True"],
        reconcile_methods=dict(collections.Counter(r["notes"].split(";")[0] for r in rec if r["match"] == "True")),
        missing_sidecar_rows=cov.get("coverage", {}).get("sidecar_missing_rows"),
        disclosures=len(disc), disclosures_not_visible=sum(d["reply_body_visible_in_transcript"] != "True" for d in disc),
        notifications_visible=notif,
        rows_without_requirement_links=sorted(r for r in runs if not (cfg.links / f"{r}.json").exists()),
        claims_runs=out["delivery_claims"]["runs"])

    # ---------------------------------------------------------------- qualitative case candidates
    out["cases"] = select_cases(cfg, runs, f2p, held, att, defs, collab)

    # ---------------------------------------------------------------- beyond the paper (report §12)
    out["extended"] = extended(cfg, runs)

    (cfg.out / "statistics.json").write_text(json.dumps(out, indent=1, default=float, ensure_ascii=False) + "\n")
    print(json.dumps({k: out[k] for k in ("outcomes", "requirements", "loss")}, indent=1, default=float)[:3000])


def extended(cfg, runs):
    """Descriptive detail the paper does not print but a reader of the report may need."""
    def q(vals):
        vals = [float(v) for v in vals if v not in ("", None)]
        if not vals:
            return None
        return dict(n=len(vals), sum=sum(vals), median=percentile(vals, 0.5), p25=percentile(vals, 0.25),
                    p75=percentile(vals, 0.75), min=min(vals), max=max(vals))
    x = {}
    tel = {f"{int(r['row']):03d}": r for r in read_csv(cfg.telemetry / "RUN_TELEMETRY.csv")}
    T = [tel[r] for r in runs if r in tel]
    x["telemetry"] = {k: q(t.get(k) for t in T) for k in (
        "tool_calls", "tool_error_calls", "chat_send_attempts", "attempt_count",
        "api_retry_count_reported", "solver_observed_message_input_tokens", "solver_observed_message_cache_read_input_tokens",
        "solver_observed_message_cache_creation_input_tokens", "solver_observed_message_output_tokens",
        "colleague_observed_phase_total_tokens", "docs_distinct_returned_entities", "board_distinct_returned_entities",
        "chat_distinct_returned_conversations", "identical_call_repeat_occurrences")}
    x["end_reasons"] = dict(collections.Counter(r["agent_end_reason"] for r in runs.values()))
    tb = collections.defaultdict(lambda: [0, 0, 0])
    for t in read_csv(cfg.telemetry / "TOOL_BREAKDOWN.csv"):
        a = tb[t["tool"]]
        a[0] += int(t["calls"] or 0); a[1] += int(t["error_calls"] or 0); a[2] += 1
    x["tools"] = [dict(tool=k, calls=v[0], errors=v[1], runs=v[2]) for k, v in sorted(tb.items(), key=lambda kv: -kv[1][0])]
    nodes = read_csv(cfg.data / "NODE_OUTCOMES.csv")
    x["failure_classes"] = {cls: dict(collections.Counter(n["failure_class"] for n in nodes
                                                          if n["node_class"] == cls and n["status"] == "failed"))
                            for cls in ("f2p", "p2p")}
    rs = cfg.data / "RUN_SUMMARY.csv"
    if rs.exists():
        S = read_csv(rs)
        x["patch"] = {k: q(r[k] for r in S) for k in ("patch_files", "patch_added", "patch_removed", "delivery_note_bytes")}
        x["per_run"] = S
    summ = cfg.review / "summary"
    if (summ / "EPISODES.csv").exists():
        x["review_episode_kinds"] = dict(collections.Counter(r["kind"] for r in read_csv(summ / "EPISODES.csv")).most_common())
        x["review_phase_tags"] = dict(collections.Counter(t for r in read_csv(summ / "PHASES.csv")
                                                          for t in r["tags"].split(",") if t).most_common())
        qi = read_csv(summ / "QUALITY_ISSUES.csv")
        x["review_quality_issues"] = [dict(category=c, severity=v, n=n, runs=len({r["row"] for r in qi if r["category"] == c and r["severity"] == v}))
                                      for (c, v), n in collections.Counter((r["category"], r["severity"]) for r in qi).most_common()]
        u = read_csv(summ / "REVIEWER_USAGE.csv")
        x["reviewer_usage"] = {k: q(r[k] for r in u) for k in ("input_tokens", "cached_input_tokens", "output_tokens")}
    return x


def select_cases(cfg, runs, f2p, held, att, defs, collab):
    """Rules (deterministic, ties broken by row):
      ask_loss          run with the most failed F2P nodes lost at 'ask'
      implement_despite run where every colleague-held requirement was obtained and most nodes lost at
                        'implement' (falls back to the highest obtained rate if no run obtained all)
      abandoned         run with the most abandoned deferral threads
    """
    ask = collections.Counter(n["row"] for n in att if n["loss_stage"] == "ask")
    impl = collections.Counter(n["row"] for n in att if n["loss_stage"] == "implement")
    fails = collections.Counter(n["row"] for n in att)
    held_by = collections.defaultdict(list)
    for r in held:
        held_by[r["row"]].append(r)
    ab = collections.defaultdict(list)
    for d in defs:
        if d["followed"] == "False":
            ab[d["row"]].append(d)
    stop = {r["row"]: r for r in read_csv(cfg.data / "stopping.csv")} if (cfg.data / "stopping.csv").exists() else {}
    asks = collections.defaultdict(list)
    ap = cfg.comm / "ASK_CHAINS.jsonl"
    if ap.exists():
        for l in open(ap):
            d = json.loads(l)
            asks["%03d" % int(d["row"])].append(d)
    t0 = {}
    for r in runs:
        p = cfg.inputs / r / "behavior" / "actions.jsonl"
        with open(p) as f:
            first = json.loads(f.readline())
        t0[r] = first.get("call_time")

    def info(row):
        hb = held_by.get(row, [])
        r = runs[row]
        fn = [n for n in att if n["row"] == row]
        c = dict(row=row, run_id=r["run_id"], task_id=r["task_id"],
                 f2p_passed=int(r["f2p_passed"]), f2p_total=int(r["f2p_total"]), f2p_pct=pct(f2p[row]),
                 colleague_held=len(hb), obtained=sum(x["acquisition"] in ("obtained", "returned_not_visible") for x in hb),
                 failed_attributed=fails[row], lost_ask=ask[row], lost_implement=impl[row],
                 lost_ask_card_raised=sum(n["ask_detail"] == "card_raised" for n in fn if n["loss_stage"] == "ask"),
                 implement_functional=sum(n["failure_class"] == "functional_failed" for n in fn if n["loss_stage"] == "implement"),
                 deferrals_abandoned=len(ab.get(row, [])),
                 deferrals_total=sum(d["row"] == row for d in defs),
                 stop_label=stop.get(row, {}).get("premature_stop"), ending_type=stop.get(row, {}).get("ending_type"),
                 known_unresolved_items=int(stop[row]["known_unresolved_items"]) if row in stop else None,
                 wall_hours=float(r["agent_wall_hours"]) if r["agent_wall_hours"] else None,
                 messages=int(r["chat_send_attempts"]))
        # evidence pointers
        ev = dict(behavior_dir=str(cfg.inputs / row / "behavior"),
                  ask_chains=f"{cfg.comm / 'ASK_CHAINS.csv'} (row == {int(row)})",
                  f2p_nodes=f"{cfg.data / 'f2p_nodes.csv'} (row == {row})",
                  deferrals=f"{cfg.data / 'deferrals.csv'} (row == {row})",
                  delivery_claims=f"{cfg.data / 'delivery_claims.csv'} (row == {row})")
        rp = cfg.review / "reviews" / "rows" / row / "report.md"
        if rp.exists():
            ev["review_report"] = str(rp)
        sol = cfg.inputs / row / "behavior" / "submission" / "SOLUTION.md"
        if sol.exists():
            ev["delivery_note"] = str(sol)
        c["evidence"] = ev
        # the most-asked undisclosed card with its question timeline
        undisclosed = {x["card_id"] for x in hb if x["acquisition"] not in ("obtained", "returned_not_visible") and x["card_id"]}
        per_card = collections.defaultdict(list)
        for a in asks.get(row, []):
            for cid in undisclosed:
                if cid in (a.get("question_text") or ""):
                    per_card[cid].append(a)
        if per_card:
            cid, qs = max(sorted(per_card.items()), key=lambda kv: len(kv[1]))
            qs = sorted(qs, key=lambda a: a["call_time"])
            c["most_asked_undisclosed_card"] = dict(
                card=cid, questions=len(qs),
                hours=[round((a["call_time"] - t0[row]) / 3600, 2) for a in qs if t0[row]],
                first_call=f"{cfg.campaign / qs[0]['call_evidence']['path']}:{qs[0]['call_evidence']['line_start']}")
        return c

    cases = {}
    if ask:
        row = max(sorted(ask), key=lambda r: (ask[r], ask[r] / max(fails[r], 1)))
        cases["ask_loss"] = dict(rule="most failed F2P nodes lost at the ask stage", **info(row))
    full = [r for r in runs if held_by.get(r) and all(x["acquisition"] in ("obtained", "returned_not_visible") for x in held_by[r])]
    pool = full or sorted(runs, key=lambda r: -float(collab.get(r, {}).get("obtained_rate") or 0))[:5]
    pool = [r for r in pool if impl[r]]
    if pool:
        row = max(sorted(pool), key=lambda r: impl[r])
        cases["implement_despite_all_obtained"] = dict(
            rule="all colleague-held requirements obtained, most nodes lost at implement" if full else
                 "highest obtained rate (no run obtained all), most nodes lost at implement", **info(row))
    if ab:
        row = max(sorted(ab), key=lambda r: (len(ab[r]), ask[r]))
        c = info(row)
        c["abandoned_threads"] = [dict(card=d["card"], budget_left_hours=float(d["budget_left_hours"]),
                                       hours_until_run_end=float(d["hours_until_run_end"]), disclosed=d["disclosed"] == "True")
                                  for d in ab[row]]
        cases["abandoned_deferrals"] = dict(rule="most abandoned deferral threads", **c)
    return cases


if __name__ == "__main__":
    main()
