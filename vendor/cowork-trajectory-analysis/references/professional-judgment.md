# Professional-judgment lenses

These lenses are a synthesis inspired by Surge AI's [DAYJOB article](https://surgehq.ai/blog/dayjob) and its [Healthcare](https://surgehq.ai/benchmarks/dayjob-healthcare) and [Finance](https://surgehq.ai/benchmarks/dayjob-finance) case analyses, read 2026-10-03. They are not an official DayJob universal trajectory rubric. DayJob primarily publishes task-specific outcome criteria and examples.

Use them within the existing 10 strategy and 6 collaboration dimensions, not as four additive scores. In relevant episodes, use the following kind tags and record both support and counterevidence:

| Tag | Observable question | Existing dimensions |
|---|---|---|
| `premise_scrutiny` | Does the solver check a consequential assumption in the handoff, colleague suggestion or older source when available evidence challenges it? | hypothesis_testing; provenance_version_reconciliation; calibration_stopping |
| `consequential_prioritization` | Does it investigate an uncertainty capable of changing the overall design/decision rather than stopping after fixing smaller issues? | decomposition_prioritization; information_value; verification_design |
| `cross_source_joining` | Does it connect related facts from different documents, owners, callers and execution records into one consistent decision? | information_integration; abstraction_transfer; scope_reconstruction |
| `evidence_to_decision` | When a relevant fact has been explicitly retrieved or noted, does the subsequent plan, code, validation or delivery decision reflect it? | feedback_adaptation; evidence_to_implementation; delivery_accountability |

DayJob examples motivate checking overlooked relations rather than counting retrieval: a currency-unit error dwarfed other detected pricing problems; a medicine already present in the model's notes was not carried into the interaction review; suspicious clinical findings did not alter an inherited treatment/discharge plan. Translate the structure of these failures to software, not the medical/financial domain rubrics themselves.

Do not reward blanket disagreement with instructions or colleagues. A solver can follow a correct inherited plan, find that a notice changes nothing, or appropriately decline unsupported changes. Impact must be grounded in the task, not invented from final test weights. If the relevant opportunity is absent or its importance cannot be established, state that explicitly instead of forcing an episode or a negative score.

Without matched human traces, discuss possible human–model contrasts as hypotheses. A plausible expert strategy is not a measured human baseline. A shorter trajectory is not necessarily a better strategy; consider the uncertainties resolved, work accomplished, failed infrastructure calls and validation scope.
