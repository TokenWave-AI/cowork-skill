# Input contract and review invocation

Use one selected run per input directory. A campaign controller supplies the identity and immutable source manifest; the skill does not assume access to the original evaluation server. Normalize a different harness explicitly rather than silently applying Claude-specific event rules. Keep the original bytes and a hash/line mapping for every normalized record.

## Required inputs

| File | Content |
|---|---|
| `INPUTS.json` | `identity` with `row`, `task_id`, `task_version`, `task_package_sha256`, `run_id`; the original public instruction; available runtime/model/scaffold/condition/budget metadata; missing-evidence notes and counts. Unknown values must be documented as unknown, never fabricated. |
| `actions.jsonl` | One record per distinct executed tool-use ID, in original order. Preserve full arguments, call/return pointers, error and missing-return states, replay occurrences and conflicts. The complete index is not a beginning/end sample. |
| `evidence.jsonl` | Complete non-heartbeat events and tool returns, one JSON object per physical line. Preserve assistant/user text and output, with an `event_id`, original record, and source mapping. No silent truncation. |

`INPUTS.identity` values must match the final report. The report's `row` is a string; the validator permits the equivalent integer in source identity. Extended runtime fields belong to the input/controller receipt rather than extra fields in the fixed report task schema.

Optional files, when observed: `sidecar.jsonl` for colleague decisions/disclosures/availability/notifications; `message_exposures.jsonl` for returned dynamic-message bodies; and `submission/` for the captured patch, solution and capture metadata. A missing sidecar or patch is not evidence that no communication or code change occurred. Explain missing files in `INPUTS.json` and the report. Do not invent an empty history to imply an observed zero.

The inspection helper expects action keys `action_id`, `order`, `canonical_tool`, `input`, `call_time`, `pairing_status`, `call_evidence` and `results`. Result pointers should retain the evidence path/physical line, tool ID and source location. It prints bounded argument previews with an explicit truncation flag; retrieve full records before using a preview to support a substantive claim.

For normalized events, keep source `raw_path`, `raw_line`, and `raw_sha256` where available. Record a JSON pointer when a single original event contains multiple tool blocks. Preserve source timestamps separately from controller-observed receipt times; narrative dates inside a document are not event times.

## Outcome and credential separation

Expose only behavior inputs to the process reviewer. Keep private final grades, gold patches, diagnosis labels, secrets, and outcome-bearing selection manifests outside that directory and deny access through the review runner. Private outcome files are joined by task/version/run identity after validation. Solver-visible test output and completion claims remain part of the behavior evidence; this is not complete outcome blindness.

Deduplicate re-archived tool IDs without treating repeated real calls as the same action. Retain unsuccessful attempts and missing returns. Preserve resumed segments belonging to this run, but do not add earlier abandoned runs merely because they concern the same task. Write source and normalization hashes before dispatch, then verify they have not changed.

## Invoke and validate

Provide the reviewer the skill path, the single behavior directory, the intended narrative language, and the output schema. Ask it to examine the complete action index and consequential full events from the beginning, middle, and end. Give a bounded budget with saved continuation records for transport interruptions. Do not let a format retry discard all prior reading.

Inspect bounded records with:

```bash
python3 scripts/inspect_trace.py /path/to/behavior --view actions --start 1 --end 30
python3 scripts/inspect_trace.py /path/to/behavior --view evidence --start 137 --end 137 --offset 0 --limit 20000
```

Run the validator using a Python environment with `jsonschema` installed:

```bash
python3 scripts/validate_report.py /path/to/report.json /path/to/behavior
```

Validation checks schema, identity, dimension sets, citation paths/physical lines, exact quoted text, referenced evidence IDs and declared action counts. It does **not** prove that a quote entails an interpretation, that the model actually read everything it claims, or that a task defect has been reproduced. Review consequential claims and counterevidence separately. In campaign exports distinguish self-reported coverage, mechanically validated citations, and independent semantic checks.
