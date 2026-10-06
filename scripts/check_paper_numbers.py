#!/usr/bin/env python3
"""Smoke-test check: compare an Opus-5.5 statistics.json against the numbers printed in the paper.

    python3 scripts/check_paper_numbers.py OUT/statistics.json --expected PAPER_NUMBERS.json

PAPER_NUMBERS.json maps each quantity name below to the value the paper prints (string). It is
distributed with the internal package (release101-20260928/opus55_paper_numbers.json), not with
this repository, because the paper is not public yet.

Exit 0 when every number matches at the paper's printed precision. Writes CHECK.md next to the JSON.
"""
import argparse
import json
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("statistics", type=Path)
    ap.add_argument("--expected", type=Path, required=True)
    a = ap.parse_args()
    p = a.statistics
    s = json.loads(p.read_text())
    expected = json.loads(a.expected.read_text())
    sel, L, C, dc, db, df = (s["outcomes"]["selected"], s["loss"], s["collaboration"], s["delivery_claims"],
                             s["delivery_claims_broad"], s["deferrals"])
    r1 = lambda x: round(x, 1)
    r0 = lambda x: round(x)
    checks = [
        ('F2P macro (%)', f"{r1(sel['macro_f2p_percent'])}"),
        ('P2P macro (%)', f"{r1(sel['macro_p2p_percent'])}"),
        ('Strict count', f"{sel['strict_count']}"),
        ('Strict (%)', f"{r1(sel['strict_percent'])}"),
        ('Median tool calls', f"{s['effort']['tool_calls']['median']:g}"),
        ('Median messages', f"{s['effort']['chat_send_attempts']['median']:g}"),
        ('Median wall-clock (min)', f"{s['cost']['wall_clock_minutes_median']:.0f}"),
        ('Colleague-held requirements', f"{s['requirements']['colleague_held']:,}"),
        ('Obtained (%)', f"{r0(s['requirements']['shares_pct']['obtained'])}"),
        ('Card raised, not disclosed (%)', f"{r0(s['requirements']['shares_pct']['card_raised_not_disclosed'])}"),
        ('Owner contacted, card not raised (%)', f"{r0(s['requirements']['shares_pct']['owner_contacted_card_not_raised'])}"),
        ('Owner never contacted (%)', f"{r0(s['requirements']['shares_pct']['owner_never_contacted'])}"),
        ('Node pass disclosed / public / undisclosed (%)', "/".join(str(r0(s['node_pass_by_state'][k]['pass_pct'])) for k in ("colleague_obtained", "public", "colleague_not_obtained"))),
        ('Paired gap mean / median (pp)', f"{r1(s['paired_disclosure_gap']['mean_pp'])}/{r1(s['paired_disclosure_gap']['median_pp'])}"),
        ('Paired gap positive / tasks', f"{s['paired_disclosure_gap']['positive']}/{s['paired_disclosure_gap']['tasks']}"),
        ('Failed F2P nodes / infra / unlinked', f"{L['failed']}/{L['excluded_infrastructure']}/{L['unmapped']}"),
        ('Attribution Discovery/Ask/Read/Implement (%)', "/".join(f"{r1(L['shares_pct'][k]):.1f}" for k in ("discovery", "ask", "read", "implement"))),
        ('Attributed (unresolved) nodes', f"{L['attributed']}"),
        ('Implement functional / build-or-load', f"{L['implement_failure_class']['functional_failed']}/{L['implement_build_or_load']}"),
        ('Ask card not raised / raised', f"{L['ask_detail']['card_not_raised']}/{L['ask_detail']['card_raised']}"),
        ('Ask table means', "/".join([f"{100*C['ask_rate']['mean']:.1f}", f"{100*C['targeting']['mean']:.1f}", f"{C['gain_per_q']['mean']:.2f}",
                   f"{100*C['followthrough']['mean']:.1f}", f"{100*C['redundancy']['mean']:.1f}", f"{100*C['unread']['mean']:.1f}"])),
        ('Ask table rho', "/".join(f"{C[m]['spearman']:+.2f}" for m in ("ask_rate", "targeting", "gain_per_q", "followthrough", "redundancy", "unread"))),
        ('Obtained-rate rho', f"{C['obtained_rate']['spearman']:+.2f}"),
        ('Effort rho messages / tools', f"{s['effort_vs_f2p']['chat_send_attempts']['spearman']:+.2f}/{s['effort_vs_f2p']['tool_calls']['spearman']:+.2f}"),
        ('Rubric dims with CI excluding 0', f"{s.get('dimensions_ci_excluding_zero')}"),
        ('Evidence-to-code rho', f"{s['dimensions']['evidence_to_implementation']['spearman']:+.2f}"),
        ('Top-rated causal/feedback/hypothesis', "/".join(str(s['dimensions'][d]['scores']['3']) for d in ("causal_debugging", "feedback_adaptation", "hypothesis_testing"))),
        ('Calibration rating 1 / assessable', f"{s['dimensions']['calibration_stopping']['scores']['1']}/{s['dimensions']['calibration_stopping']['rated_n']}"),
        ('Autonomous / median h left', f"{s['stopping']['autonomous']}/{r1(s['stopping']['autonomous_remaining_hours_median'])}"),
        ('Premature stops / median h left', f"{s['stopping']['supported']}/{r1(s['stopping']['supported_remaining_hours_median'])}"),
        ('Ask share premature / justified (%)', f"{r0(s['stopping']['loss_ask_share_by_label']['supported']['ask_pct'])}/{r0(s['stopping']['loss_ask_share_by_label']['not_supported']['ask_pct'])}"),
        ('F2P premature / justified (%)', f"{r1(s['stopping']['f2p_by_label']['supported'])}/{r1(s['stopping']['f2p_by_label']['not_supported'])}"),
        ('Claims: requirements / runs', f"{dc['scored']:,}/{dc['runs']}"),
        ('Claims strict: claimed done / failing', f"{dc['claimed_done']}/{dc['claimed_done_failed']}"),
        ('Claims strict: failed flagged open / failed', f"{dc['failed_listed_open']}/{dc['failed']}"),
        ('Claims: flagged open / reported done (% of failed)', f"{r0(dc['failed_listed_open_pct'])}/{r0(dc['failed_claimed_done_pct'])}"),
        ('Claims broad: failing / claimed done', f"{db['claimed_done_failed']}/{db['claimed_done']:,}"),
        ('Silent failures functional / build-load', f"{dc['claimed_done_failed_kind']['functional']}/{dc['claimed_done_failed_kind']['build_or_load']}"),
        ('Blind check genuine / hedged / not', "/".join(str((dc.get('blind_check') or {}).get(k, '–')) for k in ('genuine_claim', 'hedged', 'not_a_claim'))),
        ('Deferrals threads / runs', f"{df['threads']}/{df['runs_with_threads']}"),
        ('Deferrals followed / disclosed (%)', f"{df['followed']}/{df['followed_disclosed']} ({r0(df['followed_disclosed_pct'])})"),
        ('Deferrals abandoned (%) / disclosed', f"{df['abandoned']} ({r0(df['abandoned_pct'])})/{df['abandoned_disclosed']}"),
        ('Abandoned budget left / continued (h)', f"{r1(df['abandoned_budget_left_median'])}/{r1(df['abandoned_run_continued_median'])}"),
        ('Runs abandoning >=1 thread', f"{df['runs_with_abandoned']}"),
        ('Questions first fifth / after edit / last fifth (%)', f"{r0(100*s['question_timing']['first_fifth'])}/{r0(100*s['question_timing']['after_first_edit'])}/{r0(100*s['question_timing']['last_fifth'])}"),
        ('First edit at median (% of run)', f"{r0(100*s['question_timing']['first_edit_median_fraction'])}"),
        ('Rule runs / edited / median lines', f"{s['workplace_rules']['rule_runs']}/{s['workplace_rules']['edited_existing_tests']}/{s['workplace_rules']['lines_removed_median']}"),
        ('Time-limit runs without note', f"{s['workplace_rules']['time_budget_no_note']} of {s['workplace_rules']['time_budget_runs']}"),
        ('Strata edit 1k-5k / >5k F2P', f"{r1(s['strata']['edit_size']['1k-5k']['f2p'])}/{r1(s['strata']['edit_size']['>5k']['f2p'])}"),
        ('Strata web / games F2P', f"{r1(s['strata']['domain']['Web & Frontend']['f2p'])}/{r1(s['strata']['domain']['Games & Graphics']['f2p'])}"),
        ('Strict web/frontend', f"{s['strict_rows_by_domain'].get('Web & Frontend', 0)}"),
        ('Per-node reconciled runs', f"{s['coverage']['reconciled']}"),
        ('Disclosures returned / total', f"{s['coverage']['disclosures'] - s['coverage']['disclosures_not_visible']}/{s['coverage']['disclosures']}"),
        ('Distinct notices returned', f"{s['coverage']['notifications_visible']}"),
    ]
    norm = lambda x: x.replace(",", "").replace(" ", "")
    lines = ["# Smoke-test check: Opus-5.5 numbers vs paper (content/6_Results.tex, Appendix H)", "",
             "| Quantity | Paper | Pipeline | Match |", "|---|---|---|---|"]
    bad = 0
    for name, got in checks:
        if name not in expected:
            continue
        paper = expected[name]
        ok = norm(paper) == norm(got)
        bad += not ok
        lines.append(f"| {name} | {paper} | {got} | {'yes' if ok else '**NO**'} |")
    n = sum(1 for name, _ in checks if name in expected)
    lines += ["", f"{n - bad}/{n} match."]
    (p.parent / "CHECK.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
