# Evidence rules for CoWork traces

Based on inspected 2026-09-28 slim tooling. Recheck materially different versions instead of treating these as timeless API guarantees.

## Platform semantics

- Canonical workplace tools: `workplace_help`, `people_search`, `board_search`, `board_get`, `board_batch_get`, `docs_search`, `docs_get`, `docs_batch_get`, `chat_list`, `chat_search`, `chat_fetch`, `chat_send`, `chat_check_updates`, `reviews_search`, `reviews_get`, `artifacts_search`, `artifacts_get`. Normalize verified harness prefixes. Terminal, Goal and task_instruction are separate.
- Board/docs/review/artifacts retrieve authored records; they cannot update tickets, create reviews or run CI. Historical test output is not solver-executed testing. Colleagues have bounded knowledge, not independent repository execution tools.
- Search is all-term literal substring matching. Docs can match old versions but show latest snippets. IDs, metadata and full body exposure differ. Pagination/field selection can omit content; default latest is not conscious or authoritative version selection.
- Answers may appear directly in chat_send; notice bodies may appear in check_updates while read=false. chat_fetch marks all dynamic messages in the conversation read before filtering/pagination. Read/fetch counts cannot measure comprehension or even per-message body exposure.
- Direct colleague dialogue makes semantic decisions, possibly multiple items. Programmatic owner/fact/timing checks constrain them. Disclosure declarations need actual returned-text support and committed transactions; rolled-back requests are not obtained answers.
- Distinguish necessary clarification, configured related-follow-up gates and backend failure. Polling does not advance relevant follow-ups. 001 pending/remaining-follow-up hints are not uniformly exposed in other tasks.
- Notifications generally navigate to existing facts. Worktree changes advance progress; ordinary checks release at most three eligible messages per call, without an epoch=3 ceiling. Final sync can release remaining notices. Narrative dates or late-evidence prose do not prove new facts, runnable artifacts or verified conflicts. Deduplicate replayed messages.
- Public sources and owner knowledge can overlap; private-pack membership does not prove must-ask. Card assignee is not always the unique knowledge owner. Complete runtime corpora may live in images/overlays rather than the slim tree.

## Evidence hierarchy

1. Attempt: tool-use ID and inputs.
2. Actual return: paired result, error flags, content/fields/pages/truncation.
3. Exposure: relevant text appears in the saved transcript; this does not prove all later compressed contexts preserve it.
4. Specific use: concrete reference, targeted question, matching code change or designed check, not just understood or an adjacent edit.
5. Verification: relevant executed checks or authoritative grading with validity/scope limits.

Plans and reasoning text are self-reports, not psychological ground truth. A planned edit is not executed; terminal success is not test success; passing tests do not prove full coverage. Shell pipes such as pytest piped to tail may return zero with failures visible. Read command semantics and output.

## Identity, time and denominator

- Bind task_id/task_version/package_sha/run_id and runtime identity when available. Internal task IDs such as authoring are not globally unique. Recovery can change tool registration; inspect availability before attribution.
- Tool durations overlap and cannot be added as wall time. Agent time includes waiting, excludes deployment/grading. Retry backoff is not all API latency; residual time is not pure thinking time.
- Attempts may share one session. Separate actual reissued calls from duplicate/replayed archival records. Heartbeat/thinking-token events are not actions or turns.
- Behavioral claims, author facts/IU, literal atoms, cards, messages and F2P nodes have no universal one-to-one mapping. Unknown denominators remain unknown.
- Opportunity must exist and be observable. Deadline-adjacent exposure, truncation, unavailable tools and missing records warrant censored/ambiguous labels.

## Campaign integrity

Freeze manifests and skill hashes. Retry transient reviewer API failures with backoff; record refusals/access errors without evasion. Partial reviews stay partial. Aggregate by run/task, not files/messages, with valid denominator per dimension. Join outcomes after process annotation; outcome must not define a predictor being correlated with it.
