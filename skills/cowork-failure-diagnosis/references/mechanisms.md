# Failure mechanisms

Pick the label closest to the trajectory. Use `other` and say why if none fits. One requirement gets one primary
mechanism; secondary contributors go in `what_happened`.

| Stage | Mechanism | Pattern in the trajectory |
|---|---|---|
| discovery | `never_surfaced` | No record naming the requirement or its card reached the agent (no search hit, no board/doc read) |
| discovery | `surfaced_not_noticed` | A record containing it was returned but the agent never referred to it again |
| ask | `owner_never_contacted` | The holder was reachable and never messaged |
| ask | `asked_wrong_person` | The card was raised, but only with someone who does not hold it |
| ask | `asked_too_vaguely` | The owner was asked, but the question did not name the card or the decision, so no disclosure was triggered |
| ask | `deferral_not_followed` | The owner deferred and the agent never came back about this card |
| ask | `gave_up_after_failures` | Requests failed or rolled back and the agent stopped retrying while time remained |
| ask | `owner_unavailable` | The agent followed up as required and the owner still did not disclose; not the agent's fault |
| read | `reply_not_returned` | A disclosure was committed but its body never appeared in a tool result |
| read | `reply_returned_not_read` | The body was returned (for example in check_updates) and the agent did not act on it |
| implement | `answer_ignored` | The agent received the decisive fact and built something that contradicts it |
| implement | `answer_misread` | The agent built a plausible but wrong reading of an answer it quoted |
| implement | `assumed_instead_of_asking` | The agent filled a gap with its own guess (often disclosed as "my decision") instead of asking |
| implement | `partial_implementation` | The core path was built; a required branch, edge case or surface was not |
| implement | `regression_elsewhere` | Built correctly but a later change broke it (check P2P too) |
| implement | `build_or_load_failure` | The code does not compile, load or import in the grading environment |
| implement | `verified_wrong_thing` | The agent's own check passed but tested a different behaviour than required |
| implement | `out_of_time` | Work stopped at the time limit before this requirement was reached |
| infrastructure | `grader_infrastructure` | The node failed for reasons outside the agent's code (timeout, environment) |
| — | `not_determinable` | The evidence does not settle it |

Delivery-note verdicts: `accurate` (failure or uncertainty disclosed), `overstated` (reported done or confirmed
while failing), `silent` (not mentioned), `understated` (reported open but actually passing).
