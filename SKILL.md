---
name: cowork-model-report
description: Produce the SWE-CoWork paper's per-model trajectory analysis (outcomes, effort, requirement acquisition, four-stage loss attribution, collaboration metrics, optional 16-dim LLM behaviour rubric and stopping, workplace basics, strata, case candidates) for ANY model's CoWork runs, as statistics.json + report.md + paste-ready LaTeX rows + figures, plus per-run dossiers (every colleague exchange, the full transcript, requirement/node tables with grader output, patch, delivery note, reviewer report) so readers never need the raw trajectories; merges several models with cross_model.py. Use when a new model's CoWork campaign has finished and needs the same analysis as the paper.
---

# cowork-model-report

One command per stage, all wrapped by `scripts/run_model_report.py`. The scripts are the
paper's own build scripts (`analysis/observed_extended/build/*`,
`analysis/observed_*statistics.py`, `figuregen/fig_*`, and the campaign's
`prepare_inputs.py`, `extract_*.py`, `runner.py` and `summarize_reviews.py`) with paths and the
model name parametrised. Their logic and definitions are unchanged; see
`references/definitions.md`. Regression: on the Opus-5.5 campaign the pipeline reproduces every
checked paper number and byte-identical intermediate CSVs (see *Smoke test*).

The report is deliberately more detailed than the paper: §12 of `report.md` and `OUT/runs/NNN/`
keep everything the trajectories record, because readers of the report usually cannot access
the trajectories themselves. Add to the dossier rather than drop from it.

Set once:

```sh
SK=/path/to/cowork-skill
MODEL="<display name>"           # used in tables/figures
CAMP=<campaign root>             # created by stage a
BUNDLE=<public benchmark bundle> # tasks/, oracle/, MANIFEST.json
PKG=<internal data package>/release101-20260928
OUT=<output dir>                 # outputs only go here
R="python3 $SK/scripts/run_model_report.py --model $MODEL --campaign $CAMP --bundle $BUNDLE --package $PKG --out $OUT"
```

`--package` holds the per-task requirement links (F2P node → requirement → holder) and the
release task metadata. It is not in this public repository; get it from the maintainers. Both are
task-level and model-independent, but **package-specific**: reuse them for every model run on
the 20260928 package. For another package you must build new links first (see the caveats).

## Required input layout (the campaign)

```
$CAMP/manifests/manifest.json          rows[]: row, run_id, input_dir, input_files[] (sha256), outcome_path
$CAMP/inputs/NNN/behavior/             INPUTS.json, actions.jsonl, evidence.jsonl, sidecar.jsonl,
                                       message_exposures.jsonl, submission/{SOLUTION.md,model.patch}
$CAMP/inputs/NNN/outcome.json          score_snapshot {task_id, task_version, task_package_sha256,
                                       f2p_passed/total, p2p_passed/total, review_flagged, source}
$CAMP/inputs/NNN/raw-private/          job/ (STATUS, GRADE, sidecar-events, attempts/*/trajectory.jsonl),
                                       run/ (verifier/logs/**, capture/, public/instruction.md)
$CAMP/inputs/NNN/accepted-recovery-private/   only for runs whose accepted score came from a recovery
```

Stage (a) creates exactly this layout. If you already have it (as the Opus-5.5 campaign does),
skip (a). The node stage needs per-node verifier reports in `raw-private/run/verifier/logs`, or
in `accepted-recovery-private/...` when the accepted score came from a recovery.

## Stages

Each stage is idempotent. Re-running the same command skips stages whose outputs exist; add
`--force` to rebuild. `OUT/RUNLOG.jsonl` records every command, its exit code and its duration.
A bare `$R` runs the default stages: `telemetry,nodes,collab,basics,review-merge,dossier,stats,report`.

### (a) prepare: acquire and normalise trajectories (only for a new campaign)
Needs the eval status dir (`CURRENT_SCORES.csv`, plus `TRAJECTORY_INDEX.csv` with
`selected_for_current_score=True`). Pass a hosts bundle (`BUNDLE.json` with
`hosts[].ssh{host,port,user,identity_file,known_hosts}`) for remote runs. Omit it when the
trajectories are on this machine (host id `local`).
```sh
$R --stages prepare --prepare-args "--status-dir <eval status dir> \
   --hosts-bundle <BUNDLE.json> --excluded-rows 16,26 [--recoveries recoveries.json] --workers 4"
```
`--recoveries` takes a JSON list `[{row, host, run_id, job_root, run_root, record}]` for runs whose
accepted score came from a recovery.
- Runtime: SSH-bound, roughly 1–3 min per run (10–25 MB each); about 2.5 GB for 99 runs.
- Check `$CAMP/manifests/preparation-summary.json`: `ready_rows` must equal `expected_scored_rows`,
  and `identity_errors`, `parse_errors` and `missing_tool_results` should be empty or explained.
- Then run `python3 $SK/scripts/stages/prepare_inputs.py --campaign $CAMP --bundle $BUNDLE --verify`
  and confirm it exits 0.
- Resume: rerun the same command. Rows with `raw-private/ACQUISITION.json` are not re-fetched,
  and frozen behaviour files are verified rather than rewritten.

### (b) telemetry: objective telemetry and communication chains (~15 s)
```sh
$R --stages telemetry
```
Check: the stdout JSON has `all_counts_match_INPUTS: true`. Note `sidecar_missing_rows` (runs
without a sidecar get blank communication fields, not zeros). `fact_declaration_reply_visible`
numerator/denominator gives the disclosure visibility.

### (c) nodes: per-node outcomes and reconciliation (~5 s)
```sh
$R --stages nodes
```
Check that the stdout `reconciled K/N` has K = N. For every unreconciled row,
`OUT/data/RECONCILE.csv notes` gives the reason. Those rows are marked `unresolved`, excluded
from node-level analysis and claims, and listed in the report's coverage section. If a new
harness writes a verifier format the generic extractor cannot read, add a per-row rule to
`supplemental()` in `scripts/stages/build_node_outcomes.py`, as was done for 018, 043 and 078.
Never relax the exact-count requirement.

### (d) collab: acquisition, collaboration metrics, loss attribution (~4 s)
```sh
$R --stages collab
```
Check: the attribution line printed `N rows M failed nodes {...}`. `excluded_infrastructure` and
`unmapped` should be small. A large `unmapped` count means the requirement links do not fit this
package.

### (e) basics: delivery claims (strict + broad), deferrals, question timing, rule compliance (~15 s)
```sh
$R --stages basics
```
Check that `runs: K Counter({'present': ..., 'empty': ...})` matches the number of reconciled runs.
`match_method: none` should be a minority. In the deferral summary line (`N abandoned M …`), the
`told` count should be about the number of runs.

### (f) review: optional LLM rubric review (gpt-6-astra, xhigh)
Wraps the vendored 1.2 skill (`vendor/cowork-trajectory-analysis`, rubric/schema 1.0.0) with
the campaign's resume-safe runner. Reviewers read only `behavior/`, never outcomes.
```sh
$R --stages review --review-rows 1,2,3 --review-dry-run      # binding check, no API calls
$R --stages review --review-rows 11,20,46,90 --review-concurrency 4   # pilot
$R --stages review --review-concurrency 20                   # all rows
```
- Needs, from your evaluation pipeline (not in this repository): the reviewer runtime
  (`CMR_REVIEWER_RUNTIME=/path/to/reviewer_runtime.py`, which also defines the API base URL);
  an API key (`CMR_REVIEW_API_KEY`, else the runtime's key file); and a Python with
  jsonschema ≥ 4 (`CMR_REVIEW_PYTHON` or `--review-python`). Extra paths the reviewer
  sandbox must not read go in `CMR_REVIEW_DENY` (`:`-separated).
- Opus-5.5 cost for reference (99 runs): median 26 min per attempt (p90 38, max 57). There were
  1.8 attempts per row on average, counting retries and repairs. Wall time was about 3.5 h at
  concurrency 16–20. Tokens: 757 M input (732 M cached, 26 M uncached), 4.0 M output; median per
  run 7.1 M input and 32 k output. Expect roughly the same per run for other models, scaled by
  trajectory length (`telemetry/RUN_TELEMETRY.csv tool_calls`).
- Check `OUT/review/reviews/BATCH_STATUS.json`: every row should be `complete`. `held_*` and
  `needs_manual_review` rows need a human (read `rows/NNN/STATUS.json` and the attempt logs). The summarize step
  writes `OUT/review/summary/` and `OUT/data/stopping.csv`.
- Resume: rerun the same command. Completed rows are reused when the input, schema, skill and
  report hashes match.
- Skipping and merging later: the report works without this stage. Rubric, stopping and the
  behaviour figure are then omitted. Reviews produced elsewhere can be merged with
  `$R --stages review-merge,stats,report --reviews /path/to/reviews`, a directory containing
  `rows/NNN/{STATUS.json,report.json}`.

### (h) dossier: per-run detail (~15 s)
```sh
$R --stages dossier [--dossier-result-chars N]
```
Writes `OUT/runs/NNN/{RUN.md, conversation.md, transcript.md, REQUIREMENTS.csv, NODES.csv,
SOLUTION.md, model.patch, PATCH_STAT.csv, review.md, review.json}`, `OUT/runs/INDEX.md` and
`OUT/data/RUN_SUMMARY.csv`. Transcripts keep every tool result in full unless
`--dossier-result-chars N` clips them to head+tail (99 runs: about 190 MB in full).
Rerun after `review-merge` so dossiers include the reviewer's report.
Checks: `INDEX.md` lists every run; open one `RUN.md` and its `conversation.md`; failed nodes
without grader output mean the verifier format is not recognised by `grader_output()`.

### (g) stats and report (~10 s)
```sh
$R --stages stats,report [--claims-blind-check blind.csv]
```
Produces `OUT/statistics.json`, `OUT/report.md`, `OUT/paper_rows.tex`, `OUT/tables/*.tex` and
`OUT/figures/*.{pdf,png,svg}`. Run `dossier` first: report §12 (beyond the paper) reads
`data/RUN_SUMMARY.csv`. Every number in `report.md` is a statistics.json field
(`templates/report.md.j2`). `references/paper_mapping.md` says which field fills which paper
cell or sentence.

Checks:
- Open the four PNGs and confirm that labels do not collide.
- Read report §11 (coverage): unreconciled rows, missing sidecars, and runs without links.
- Read report §10 (case candidates) and the case's `runs/NNN/` before quoting it.
- Optional blind check of claim precision: sample about 30 rows of `OUT/data/delivery_claims.csv`
  with `claim_class=claimed_done, delivered=False`. Have a reader judge them against the full note
  as genuine_claim / hedged / not_a_claim, save `row,card_id,verdict,quote`, and pass the file
  with `--claims-blind-check`.

### Several models
```sh
python3 $SK/scripts/cross_model.py $OUT_A $OUT_B $OUT_C --dest $DEST
```
Produces multi-model rows for Tables main / cost / attrib (with a Mean row), a full ask table, a
workplace-basics comparison and a strata × model F2P table. Figures: stacked loss stages,
acquisition, claims honesty, and outcomes per model.

## Smoke test / regression
```sh
$R --reviews $CAMP/reviews --claims-blind-check $PKG/opus55_delivery_claims_blind_check.csv
    # with MODEL=Opus-5.5 and CAMP = the Opus-5.5 campaign
python3 $SK/scripts/check_paper_numbers.py $OUT/statistics.json --expected $PKG/opus55_paper_numbers.json
    # exit 0 = every paper number reproduced
```
The full non-LLM pipeline takes about a minute for 99 runs, with roughly 0.3 GB peak RSS.

## Caveats
- Requirement links are package-specific. A different task package or version needs new
  `requirement_links/NNN.json` and `release101_tasks.json`; the stats stage lists rows without
  links. The links were built from per-task contract maps, requirement YAML and test sources
  (ask the maintainers for the tooling).
- The delivery-claims classifier is a keyword heuristic. In the paper's blind check about a third
  of sampled silent failures were hedged elsewhere or not claims, so read claimed-done counts as
  an upper bound and report both the strict and the broad reading.
- Colleague-call failure reporting is intentionally excluded (dropped from the paper).
- Rubric scores are model annotations without human agreement; correlations are exploratory.
- Remaining-budget numbers assume each run's `budget_seconds` (8 h); question timing uses
  first-to-last action time.
