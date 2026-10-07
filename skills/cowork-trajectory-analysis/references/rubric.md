# Rubric 1.0.0: observable strategy and collaboration

The unit is a selected task-run with nested episodes. A card, requirement claim, message, tool call, and test node are different units. No total intelligence score is defined. Report dimensions separately, considering opportunity, task size, outcome coverage and runtime faults.

## Shared anchors

Use a 0–3 score only for an observable opportunity with enough evidence:

- **0 — demonstrated ineffective handling:** relevant actions are observed but fail to address an available, identifiable need; cite the opportunity and behavior. Not simply no messages or a failing final test.
- **1 — partial/reactive handling:** useful action with concrete unresolved gaps or avoidable repetition supported by the trace.
- **2 — effective handling:** appropriate evidence/actions achieve the local purpose; limited gaps are made explicit. Efficient exhaustive checking may qualify.
- **3 — strong adaptive handling:** well-supported choices connect multiple steps, resolve a consequential uncertainty or shared cause, and adapt or verify appropriately. Cite a complete enough episode, not eloquent planning alone.

Use null for `not_observed`, `not_applicable`, `censored`, or `ambiguous`. Observed score 0 means observed problematic conduct. Score 3 does not require a near-perfect final outcome, and a correct final patch does not automatically earn 3.

Confidence: high = direct, complete, consistent evidence; medium = supported chain with a stated limitation; low = partial or ambiguous interpretation. Hypotheses about ability remain interpretive.

## Ten strategy dimensions (exact IDs)

| ID | Capability | Effective/strong anchors | Ineffective/partial patterns to investigate |
|---|---|---|---|
| `search_strategy` | Adapt search breadth, depth, source and query. | Overview leads to scoped investigation; no-hit results lead to sensible changes; exhaustive scans used when justified. | Repeated identical no-hit queries; unbounded acquisition without visible use; premature narrowing despite contradictory scope. Large retrieval alone is not failure. |
| `decomposition_prioritization` | Break work into dependencies and choose consequential work. | Address shared prerequisites, risky interfaces or blocking assumptions before dependent implementation; actual actions follow or revise plans. | Cosmetic/easy work while acknowledged blocking contracts remain unresolved; rework traceable to skipped dependencies. |
| `hypothesis_testing` | Form alternatives and obtain discriminating evidence. | Reproduction, question or inspection rules out a concrete explanation; contradictory evidence updates the hypothesis. | Unfalsifiable assertions; repeated edits without narrowing causes; claiming confirmation from non-discriminating output. |
| `information_value` | Reduce decision-relevant uncertainty. | Focused question/inspection resolves a pivotal ambiguity or rules out a source; sufficient context for actionable answers. | Accumulating background while a specific decision remains open; redundant requests without confirmation/recovery purpose. Negative results can be useful. |
| `abstraction_transfer` | Recognize shared constraints and generalize appropriately. | Link multiple affected paths to a shared mechanism; check exceptions. | Per-case hardcoding despite demonstrated common structure; overgeneralization ignoring known exceptions. Gold similarity is not the criterion. |
| `causal_debugging` | Trace mechanism from input through code to effect. | Minimal reproductions, call/data-flow inspection, causal isolation, targeted fix and confirming checks. | Editing near error text without mechanism; suppressing symptoms; unrelated changes without evidence. |
| `feedback_adaptation` | Change course after relevant feedback. | Methods, assumptions or checks change; persistence is appropriate when conditions improve. | Same failed action under unchanged conditions/purpose; abandoning viable routes after recoverable errors. Provider outages are separate. |
| `information_integration` | Maintain usable constraints and open-work state. | Notes or explicit synthesis connect sources and later actions; reuse earlier findings accurately across interruptions. | Contradictory claims, dropped acknowledged obligations, repeated rediscovery without evident recovery need. Do not diagnose internal forgetting. |
| `verification_design` | Design checks capable of exposing implementation errors. | Counterexamples, boundaries, callers, integration and regressions; accurate interpretation of output. | Assertions merely mirror implementation; historical green logs substitute for current tests; failed output reported as passing. |
| `calibration_stopping` | Distinguish uncertainty from confirmation and end accurately. | Limitations explicit; claims match checks; important known gaps receive action or justified disposition. | Unsupported confidence, known failures omitted, autonomous stop with actionable acknowledged gaps. Short duration alone is not negative. |

## Six collaboration dimensions (exact IDs)

| ID | Focus and opportunity |
|---|---|
| `scope_reconstruction` | Establish current scope; distinguish active, cancelled, duplicate and neighboring work. Exploration outside target is not itself out-of-scope implementation. |
| `provenance_version_reconciliation` | Resolve actual version/source/revision conflicts with evidence. Latest does not necessarily mean authoritative; absent conflict opportunity means not applicable. |
| `owner_question_followthrough` | Route concrete questions to valid accessible sources; follow referrals, answer necessary clarifications and continue relevant deferred requests. Multiple valid sources may exist. |
| `notification_handling` | After body exposure, investigate the target or establish already-known, irrelevant or unverifiable status. Do not demand edits or repeated questions for every notice. |
| `evidence_to_implementation` | Link obtained/confirmed constraints to production edits and meaningful checks. Temporal adjacency alone is not proof of use or influence. |
| `delivery_accountability` | Final claims match changes, validation scope and remaining issues. Control-plane completion is independent of correctness. |

Apply shared anchors with exact examples. These overlap with strategy dimensions by design; do not sum them as independent items.

## Phases, episodes, endings

Describe phases with multiple tags where appropriate: `broad_mapping`, `directed_search`, `hypothesis_driven`, `implementation_first`, `dependency_first`, `example_driven`, `generalization`, `trial_and_error`, `verification_first`, `recovery`, `closeout`, `mixed`. Tags are descriptive, not ranked.

Episodes connect uncertainty/goal, available evidence, attempted action, actual return and subsequent response. Include representative beginning/middle/end episodes and counterexamples to the dominant profile. Do not manufacture episodes to meet a quota. Inspect materials behind the strongest positive and negative claims.

Ending types: `autonomous_completion`, `time_budget`, `provider_interruption`, `tool_or_environment_failure`, `mixed`, `unknown`. Premature-stop verdict: `supported`, `not_supported`, `uncertain`, `not_applicable`. Support requires autonomous cessation plus an actionable important unresolved issue and assessment of competing explanations.

Quality categories: `task_contract`, `scoring`, `colleague`, `provider`, `harness_tools`, `environment`, `suspected_leakage`, `telemetry`. State observed versus suspected, local scope, evidence, potential impact and confirmation needed. One run does not establish prevalence.

Human–model differences are hypotheses without matched human traces. Calling a pattern expert-like does not prove humans use it more often.
