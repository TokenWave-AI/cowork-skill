# Paper mapping: which statistics.json field fills which paper cell or sentence

Paths are into `OUT/statistics.json` (`s`). "Results" = `content/6_Results.tex`, "App. H" =
`content/C_ObservedTrajectories.tex`, "App. results" = `content/A_Appendix.tex`.
LaTeX rows are emitted ready-made in `OUT/paper_rows.tex`. Complete per-model tabulars are in
`OUT/tables/`, and multi-model versions come from `scripts/cross_model.py`.
Formatting: `%.1f` for table percentages; integers for the rounded percentages in the prose.

## Tables

| Paper table (label / file) | Cell | Field |
|---|---|---|
| Table observed-outcomes (`tables/table_observed_outcomes.tex`) | Selected n, F2P, P2P, Strict % (count) | `outcomes.selected.{n,macro_f2p_percent,macro_p2p_percent,strict_percent,strict_count}` |
| Table main (`tab:main`, inline in Results) | CoWork F2P | `outcomes.selected.macro_f2p_percent` |
| | CoWork Strict | `outcomes.selected.strict_percent` (the paper prints % here) |
| | Oracle-Spec F2P/Strict/pass³, CoWork pass³, Δ_F2P | not produced (`\tbd`): needs Oracle-Spec runs and seeds |
| Table cost (`tab:cost`) | CoWork Wall-clock (min) | `cost.wall_clock_minutes_median` (= `effort.agent_wall_hours.median`×60) |
| | CoWork Tool calls | `cost.tool_calls_median` |
| | Tokens | not produced (`cost.tokens_k_median` = null) |
| Table observed-effort (App. H, `tables/table_observed_effort.tex`) | four rows | `effort.{tool_calls,chat_send_attempts,distinct_colleague_recipients_attempted,agent_wall_hours}.{n,median,p25,p75}` |
| Table attrib (`tab:attrib`, `tables/table_observed_attrib.tex`) | Discovery/Ask/Read/Implement % | `loss.shares_pct.{discovery,ask,read,implement}` |
| | Unresolved | `loss.attributed` |
| | Agreement (κ) | not produced |
| Table ask (`tab:ask`, `tables/table_observed_ask.tex`) | Ask rate, Targeting, Follow-thr., Redundancy, Unread | `100 × collaboration.{ask_rate,targeting,followthrough,redundancy,unread}.mean` |
| | Gain/Q | `collaboration.gain_per_q.mean` |
| | Spearman row | `collaboration.<m>.spearman` |
| Table observed-dimensions (App. H) | Rated n, 0–3, Unrated | `dimensions.<d>.{rated_n,scores,unrated_n}` |
| Table strata (`tab:strata`, App. results) | n, F2P, Strict, Disclosed | `strata.{verifier_nodes,edit_size,language,domain}.<stratum>.{n,f2p,strict,obtained}` |

## Figures (`OUT/figures/`, same file names as the paper)

| Paper figure | File | Data |
|---|---|---|
| Fig. requirement-flow (a) | `fig_requirement_flow.pdf` | `requirements.acquisition` |
| (b) | | `node_pass_by_state` |
| (c) | | `loss.stages`, `loss.ask_detail` |
| Fig. effort-score (a–c) | `fig_observed_effort.pdf` | `data/runs.csv`, `effort_vs_f2p` |
| (d) | | `outcomes.*` |
| (e) | | `data/stopping.csv`, `stopping.supported_remaining_hours_median` |
| Fig. behaviour | `fig_observed_behaviour.pdf` | `dimensions.<d>.{scores,unrated_n,spearman,ci95,ci_excludes_zero}` (only when reviews are merged) |
| Fig. basics (a) | `fig_workplace_basics.pdf` | `delivery_claims.table` |
| (b) | | `deferrals` |
| (c) | | `question_timing.deciles` |

## Sentences in Results

| Sentence (paper section) | Field |
|---|---|
| §6.1 macro F2P / P2P and number of tasks passing every node | `outcomes.selected.*` |
| §6.1 median per-run F2P, runs ≥90%, runs <25% | `outcomes.{median_f2p_percent,runs_f2p_ge_90,runs_f2p_lt_25}` |
| §6.1 runs preserving every P2P node | `outcomes.runs_p2p_all_preserved` |
| §6.1 median tool calls, messages, distinct colleagues, hours | `effort.*.median` |
| RQ2 colleague-held requirements and share obtained | `requirements.colleague_held`, `requirements.shares_pct.obtained` |
| RQ2 shares: card raised / owner contacted, card not raised / owner never contacted | `requirements.shares_pct.{card_raised_not_disclosed,owner_contacted_card_not_raised,owner_never_contacted}` |
| RQ2 first-question targeting rate | `collaboration.targeting.mean` |
| RQ2 node pass rate by information state | `node_pass_by_state.{colleague_obtained,public,colleague_not_obtained}.pass_pct` |
| RQ2 within-task paired gap, Wilcoxon | `paired_disclosure_gap.{mean_pp,median_pp,positive,tasks,wilcoxon_p}` |
| RQ2 failed nodes, infrastructure exclusions, unlinked, attributed | `loss.{failed,excluded_infrastructure,unmapped,attributed}` |
| RQ2 implement share, functional vs build/load | `loss.shares_pct.implement`, `loss.implement_failure_class.functional_failed`, `loss.implement_build_or_load` |
| RQ2 ask share, card never raised vs raised | `loss.shares_pct.ask`, `loss.ask_detail.{card_not_raised,card_raised}` |
| RQ2 discovery and read shares, disclosures not returned | `loss.shares_pct.discovery`, `coverage.disclosures_not_visible` |
| RQ3 ask rate, targeting, max abs ρ, obtained-rate ρ | `collaboration.*`, `collaboration_max_abs_rho_excl_obtained` |
| RQ3 effort–F2P correlations | `effort_vs_f2p.*.spearman` |
| RQ3 dimensions whose CI excludes zero | `dimensions_ci_excluding_zero`, `dimensions_significant_ranked` |
| RQ3 dimensions most often rated 3 | `dimensions_top_rated3` |
| RQ3 lowest-rated dimension | `dimensions_lowest_mean` |
| Stopping: autonomous ends, hours left, time-limit, mixed | `stopping.{autonomous,autonomous_remaining_hours_median,time_budget,mixed}` |
| Stopping: premature stops and hours left | `stopping.{supported,supported_remaining_hours_median}` |
| Stopping: ask-share and F2P by stop label | `stopping.loss_ask_share_by_label.*.ask_pct`, `stopping.f2p_by_label` |
| §6.5 briefs asking for a delivery note | `workplace_rules.told_delivery_note` |
| §6.5 requirements with tests, runs | `delivery_claims.{scored,runs}` |
| §6.5 failed requirements flagged open / reported done | `delivery_claims.{failed_listed_open_pct,failed,failed_claimed_done_pct}` |
| §6.5 reported done that fail | `delivery_claims.{claimed_done,claimed_done_failed,claimed_done_failed_pct}` |
| §6.5 broad reading | `delivery_claims_broad.{claimed_done_failed,claimed_done,claimed_done_failed_pct}` |
| §6.5 blind check | `delivery_claims.blind_check` (needs `--claims-blind-check`) |
| §6.5 silent failures by kind | `delivery_claims.claimed_done_failed_kind.{functional,build_or_load}` |
| §6.5 deferral threads and runs | `deferrals.{threads,runs_with_threads}` |
| §6.5 followed / disclosed / abandoned | `deferrals.{followed,followed_disclosed,followed_disclosed_pct,abandoned,abandoned_pct,abandoned_disclosed}` |
| §6.5 budget left at abandonment, time worked after, runs abandoning | `deferrals.{abandoned_budget_left_median,abandoned_run_continued_median,runs_with_abandoned}` |
| §6.5 question timing | `question_timing.{first_fifth,first_edit_median_fraction,after_first_edit,last_fifth}` |
| §6.5 test-rule compliance | `workplace_rules.{rule_runs,edited_existing_tests,lines_removed_median,deleted_test_files}` |
| §6.5 time-limit runs without a note | `workplace_rules.{time_budget_no_note,time_budget_runs}` |
| Strata sentences | `strata.edit_size`, `strata.domain`, `strict_rows_by_domain` |
| §6.10 qualitative cases | `cases.{ask_loss,implement_despite_all_obtained,abandoned_deferrals}` (candidates only; check the evidence) |

## Appendix H sentences

| Sentence | Field |
|---|---|
| Link confidence of F2P nodes | `mapping_confidence_all_nodes` (no matching requirement = `none` + `unmapped`) |
| Pass rates on high-confidence links only | `node_pass_by_state_high_conf` |
| Runs whose per-node results reproduce the score; unresolved nodes | `coverage.reconciled`, `coverage.unreconciled`, `f2p_nodes.unresolved` |
| Disclosures returned to the agent | `coverage.{disclosures,disclosures_not_visible}` |
| Distinct notices returned | `coverage.notifications_visible` |

## Not in the paper (report §12 and `runs/NNN/`)

Report §12 and the per-run dossiers carry descriptive detail that no paper cell uses:
`extended.telemetry` (tool calls, tool errors, attempts, API retries, observed solver and
colleague tokens, distinct records read, repeated calls), `extended.end_reasons`, `extended.tools`,
`extended.failure_classes`, `extended.patch`, reviewer episode kinds / phase tags / quality issues /
reviewer cost, and `extended.per_run` (= `data/RUN_SUMMARY.csv`).

## Intentionally not reported
- Colleague-call failure classes (answered / colleague-model failure / service unavailable /
  rejected). The paper does not report them, and `export_extended.py` does not produce
  `colleague_calls.csv`.
- Oracle-Spec, pass^k, token totals and κ agreement: these need experiments this pipeline does
  not have.
