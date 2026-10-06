# Definitions

Part A follows the paper's Appendix H ("Observed Runs: Measurement Details") and the
definition paragraphs of the paper's analysis READMEs, with the paper's own counts removed.
Part B gives the exact operational rules as implemented in `scripts/stages/*.py`. The code is
the paper's build scripts with only paths parametrised, so the definitions are unchanged.

## A. Paper text (Appendix H and analysis READMEs)

**Cohort.** The analysis uses one scored CoWork run of the model for each task of the package
(tasks without a scored run are listed, not imputed). Each record carries its task version, package hash, run ID, requested models,
scaffold version, runtime revision and budget. A run that recovered from a provider interruption
is one run, not a replication. Seeds and exact cumulative token counts were not recorded, so
pass^k and token columns remain empty.

**Effort** (Table observed-effort caption). Quantiles use linear interpolation. Tool calls and
messages count attempts, including returned errors; recipients are distinct colleagues
contacted. Wall time includes waits and retries and excludes environment setup and final
grading.

**Outcomes** (snapshot README). F2P and P2P percentages are the arithmetic means of per-task
passed/total fractions (macro averages). They are not pooled test-node success rates. Strict
success means both F2P and P2P numerators equal their respective denominators for the same task.
The paper does not report a sensitivity cohort; `statistics.json` still records
`outcomes.sensitivity` (excluding the package's preexisting quality-flagged rows) for internal
checks only. Do not put it in a report or table.

**Linking tests to requirements.** Every F2P node was linked to the requirement(s) it tests by
matching per-node requirement files, test sources and upstream change titles against the
Oracle-Spec of the same package, with a confidence of high, medium or low (or no matching
requirement). The report repeats the node pass rates on high-confidence links only as a
robustness check. Per-node grading results are recovered from verifier reports and must
reproduce the per-run F2P and P2P counts exactly; a run for which no per-node record does so is
excluded from node-level analyses.

**Disclosure and visibility.** The workplace service records every requirement it releases to
the agent as a committed disclosure, linked to the question that triggered it. A disclosure
counts as reaching the agent when the reply body appears in a tool result of the saved
trajectory. Questions are linked to cards by the card
identifiers they name. A requirement whose card the agent never named, but whose owner it did
contact, is counted as *owner contacted, card not raised*.

**Loss stage** (observed_extended README). A requirement is *disclosed* when the workplace
service committed a disclosure of it to the agent; it *reached the agent* when the reply body
appears in a tool result. Loss stage is the earliest of discovery / ask / read / implement over a
node's linked requirements; nodes failed by grader infrastructure are excluded.
Table attrib caption: *Discovery*: no record carrying the requirement reached the agent. *Ask*:
the requirement was held by a colleague and never disclosed. *Read*: disclosed, but the reply
never reached the agent. *Implement*: the requirement reached the agent and the behaviour is
still wrong. *Unresolved* counts failed F2P nodes with a linked requirement, excluding nodes
failed by grader infrastructure and nodes with no linked requirement.

**Behaviour annotation.** The reviewer applies ten strategy and six collaboration dimensions to
observable actions and their results. Each dimension has its own ordinal 0–3 anchors; a missing
opportunity yields no rating rather than a zero. All reports pass schema and evidence-reference
validation. The stop judgement requires an autonomous end, a known in-scope gap, an available
next step, and no later evidence that closes the gap. Ratings are not summed across dimensions.

**Delivery claims.** For each requirement we located its card identifier, or its topic when the
card is not named, in the delivery note and in the agent's final completion summary, and
classified the surrounding sentence, table row or section as reporting the requirement done,
open (pending, unconfirmed, partial, an own assumption, or listed under an open-items heading)
or not mentioned. Topic matches under an open-items heading count as open even when the card is
named elsewhere, and a requirement listed as open in any of these ways counts as open. Wide card
ranges in source lists count as a claim only when the sentence quantifies over all of them. The
main figures treat rows of "confirmed requirements" tables as claims only when they also state an
implementation; the broader reading is reported alongside. Runs that recovered from an
interruption are read from the recovered note. Precision is checked by an independent reader
who judges a random sample of silent failures against the full notes (`--claims-blind-check`).

**Deferrals and rules.** A deferred thread is an owner–card pair whose first reply deferred the
answer. The agent follows up when it later messages the same owner naming the same card, or when
the environment counts a qualifying follow-up for that thread. Budget left is measured against
the eight-hour budget at the time of the deferral. Test-rule compliance counts changed or
removed lines in existing test source files of the submitted patch, for runs whose brief states
the test-preservation rule without a migration exception.

**Notifications.** The report counts the distinct mid-build notices the environment released
that were returned to the agent. A notice points to existing evidence rather than adding a
requirement, so notices do not enter the requirement count.

**Strata** (Table strata caption). F2P is macro-averaged within each stratum; Strict counts
tasks with every node passing; Disclosed is the mean share of colleague-held requirements
obtained. Edit size counts production lines added by the reference change.

## B. Operational rules (as implemented)

### Per-run snapshot (`stages/build_runs.py`)
- Unit: one selected scored run per task (`manifests/manifest.json` rows). Identity:
  row + run_id + task_version + task_package_sha256.
- F2P/P2P counts come from `inputs/NNN/outcome.json` `score_snapshot`, which is authoritative
  after accepted recoveries. `preexisting_quality_flag` = `score_snapshot.review_flagged`.
- `tool_calls`: unique `tool_use` IDs (`behavior/actions.jsonl`). `chat_send_attempts`:
  actions whose `canonical_tool == chat_send` (errors included). Distinct recipients: distinct
  `input.recipient_id`.
- `agent_elapsed_seconds` and `agent_end_reason` come from `INPUTS.json runtime.status`.
- Remaining budget = `budget_seconds`/3600 − wall hours (8 h for the 20260928 package).

### Per-node outcomes (`stages/build_node_outcomes.py`, unchanged)
- Evidence directory: if the score source says "accepted recovery", use
  `accepted-recovery-private/run/verifier/logs` (or the original evidence it reused).
  Otherwise use `raw-private/run/verifier/logs`.
- Candidate files: ctrf.json first, then other JSON/JSONL, then text logs. A generic extractor
  matches node IDs by exact match, config aliases, canonical form, prefix stripping, and finally
  unique numeric IDs.
- A candidate is accepted only if the reconstructed F2P/P2P pass counts equal the reported
  counts exactly and it covers ≥ 50% of nodes. Absent nodes count as failed (`not_reported`).
  Per-row supplemental evidence rules for formats the generic extractor cannot read live in
  `supplemental()` (documented in the code).
- A run with no reproducing evidence gets every node marked `unresolved`. Such runs are excluded
  from all node-level analyses and from the delivery-claims stage.
- Failure classes: explicit grader labels first, message text as fallback. The classes are
  `functional_failed`, `solver_compile_error`, `solver_runtime_or_load_error`, `timeout`,
  `infrastructure_or_blocked`, `unspecified` and `not_reported`. Build/load =
  compile + runtime_or_load.

### Requirement acquisition (`stages/collab_metrics.py`, unchanged)
Per colleague-held requirement (holder ≠ public in `requirement_links/NNN.json`):
- `obtained`: a committed disclosure exists and its reply body is visible in the transcript.
- `returned_not_visible`: disclosed, but the reply is not visible.
- `asked_owner_about_card`: not disclosed, and a question to its owner names the card.
- `asked_wrong_person_about_card`: the card is named only to others.
- `contacted_owner_not_card`: the owner was messaged, but never about this card.
- `owner_never_contacted`.

Paper groupings: "obtained" = obtained + returned_not_visible; "card raised" = asked_owner +
asked_wrong_person.

Per-run metrics:
- ask_rate = asked / colleague-held, where asked = disclosed or the card was raised with its
  owner.
- targeting = share of owner-held cards whose *first* naming question went to the owner.
- gain_per_q = disclosures / chat_send attempts.
- followthrough = obtained / asked.
- redundancy = share of card-naming questions whose cards were all already disclosed.
- unread = disclosures without a visible reply / disclosures.
- obtained_rate = disclosed / colleague-held.

The reported values are means over runs, each with Spearman ρ against per-run F2P.

### Loss attribution (`stages/attribution.py`, unchanged)
Per failed F2P node with failure class not in {infrastructure_or_blocked, timeout}, take the
earliest stage over its linked requirements:
- public requirement: `implement` if its card appears in any tool result or a public task
  document was fetched, else `discovery`.
- colleague-held: `implement` if disclosed and visible; `read` if disclosed but not visible;
  `ask` if the card appeared in a tool result; else `discovery`.

Nodes without a linked requirement are `unmapped`. The ask detail is `card_raised` if any
undisclosed linked requirement was raised with an owner or someone else, else `card_not_raised`.
Node information state: `public` (all linked requirements public), `colleague_obtained` (all
colleague-held linked requirements obtained), `colleague_not_obtained`, or `unmapped`. The paired
gap is the per-task mean pass(obtained) − pass(not obtained) over tasks having both, tested with
a Wilcoxon signed-rank test.

### Delivery claims (`stages/build_claims.py`, unchanged keyword rules)
- Sources: `behavior/submission/SOLUTION.md`, or the recovered note, plus the last
  `update_goal(status=complete)` summary.
- Strict reading: `IMPL_HEAD` = implementation / change / verified headings. The broad reading
  (`CLAIMS_BROAD=1`) adds "confirmed requirements" / contract / per-card / chain headings.
- `delivered` = all of a requirement's F2P nodes pass. A requirement counts as failed if any of
  its nodes fails.
- Silent failure = claimed_done ∧ failed. "Not flagged open" = failed − claimed_partial_or_open.
- Precision caveat: in the paper's blind check about a third of sampled silent failures were
  hedged elsewhere or not claims, so read claimed-done counts as an upper bound.

### Deferrals, timing, rules (`stages/build_workplace_basics.py`, unchanged)
- A thread is (row, owner, card) with an `availability_deferred` event with `first_defer=true`.
  Its time is the call time of the linked ask.
- followed = a later chat_send to the same owner naming the card, or an
  `availability_followup_counted` event. disclosed = an `availability_opened` event for the
  thread.
- budget_left = 8 − hours since the first action; hours_until_run_end = time to the last action.
- Question deciles: chat_send call time / run duration (first to last action).
- First edit: first terminal action matching the edit regex (apply_patch, sed -i, heredoc or
  redirect to a source file).
- Rule runs: the brief text actually returned to the agent states "existing tests must not be
  modified/deleted" (EN/ZH) and contains no migration allowance.
- Violation: the submitted patch changes or removes lines (or deletes a file) in an existing
  test *source* file (`patch_rules.categorise == test`, code extension, not a new file).
- No delivery note: SOLUTION.md is under 50 bytes in a run that was told to write one.

### Stopping (`stages/summarize_reviews.py` → `data/stopping.csv`)
- `ending_type` ∈ {autonomous_completion, time_budget, mixed}.
- `premature_stop` ∈ {supported, uncertain, not_supported, not_applicable} comes from the
  reviewer's `stop_assessment`.
- "Premature" = supported.
- Remaining hours are taken over autonomous completions.

### Rubric correlations (`stages/compute_statistics.py`)
- Spearman ρ of each 0–3 dimension score with per-run F2P over the rated runs.
- 95% CI from a 1,000-resample bootstrap with `numpy.random.default_rng(7)`. Dimensions are
  drawn in the fixed order of the paper figure, which is identical to
  `figuregen/fig_observed_behaviour.py`.

### Strata (`stages/compute_statistics.py`, from `package/.../release101_tasks.json`)
- Verifier nodes: < 28 / 28–35 / > 35.
- Production lines added by the reference change: < 1k / 1k–5k / > 5k.
- Language groups and top-4 domains, otherwise "Other".

### Case candidates (deterministic; ties broken by row)
1. Most failed F2P nodes lost at *ask*.
2. Every colleague-held requirement obtained, then the most nodes lost at *implement*. If no run
   obtained everything, fall back to the five runs with the highest obtained rate.
3. Most abandoned deferral threads.

The paper's cases were hand-picked with other considerations; the rules give candidates only.
