#!/usr/bin/env python3
"""Per-run snapshot (one row per selected scored run) built from the campaign inputs.

Replaces the paper's frozen analysis/observed_opus55_20261005/runs.csv for an arbitrary model.
Field definitions are identical to that snapshot (see references/definitions.md):
  f2p/p2p counts       outcome.json score_snapshot (authoritative accepted score)
  preexisting flag     score_snapshot.review_flagged
  tool_calls           unique tool_use IDs in behavior/actions.jsonl
  chat_send_attempts   actions with canonical_tool == chat_send (errors included)
  distinct recipients  distinct chat_send input.recipient_id
  elapsed / end reason INPUTS.json runtime.status (wall time incl. waits/retries)
Rubric scores are NOT here; they are joined from review/summary/RUN_ANALYSIS.csv in the stats stage.
Writes OUT/data/runs.csv.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import config, write_csv  # noqa: E402

FIELDS = ['row', 'run_id', 'task_id', 'task_version', 'task_package_sha256', 'solver_model_requested',
          'solver_effort_requested', 'scaffold', 'scaffold_version', 'budget_seconds',
          'colleague_model_requested', 'f2p_passed', 'f2p_total', 'f2p_rate', 'p2p_passed', 'p2p_total',
          'p2p_rate', 'preexisting_quality_flag', 'agent_elapsed_seconds', 'agent_wall_hours', 'tool_calls',
          'chat_send_attempts', 'distinct_colleague_recipients_attempted', 'agent_end_reason']


def main():
    cfg = config()
    man = cfg.manifest()
    out = []
    for item in sorted(man['rows'], key=lambda x: int(x['row'])):
        row = '%03d' % int(item['row'])
        d = Path(item['input_dir'])
        inp = json.loads((d / 'INPUTS.json').read_text())
        oc = json.loads((cfg.inputs / row / 'outcome.json').read_text())
        sc = oc['score_snapshot']
        for k in ('task_id', 'task_version', 'task_package_sha256'):
            assert sc[k] == inp['identity'][k], (row, k)
        st = inp['runtime']['status']
        sel = oc.get('selected_status') or {}
        acts = [json.loads(l) for l in open(d / 'actions.jsonl')]
        rec = {a['input'].get('recipient_id') for a in acts
               if a.get('canonical_tool') == 'chat_send' and isinstance(a.get('input'), dict)} - {None}
        fp, ft, pp, pt = (int(sc[k]) for k in ('f2p_passed', 'f2p_total', 'p2p_passed', 'p2p_total'))
        el = st.get('agent_elapsed_seconds')
        out.append(dict(
            row=row, run_id=item['run_id'], task_id=sc['task_id'], task_version=sc['task_version'],
            task_package_sha256=sc['task_package_sha256'],
            solver_model_requested=sel.get('model', ''), solver_effort_requested=sel.get('effort', ''),
            scaffold=sel.get('scaffold', ''), scaffold_version=sel.get('scaffold_version', ''),
            budget_seconds=sel.get('budget_seconds', ''), colleague_model_requested=sel.get('colleague_model', ''),
            f2p_passed=fp, f2p_total=ft, f2p_rate=fp / ft if ft else '',
            p2p_passed=pp, p2p_total=pt, p2p_rate=pp / pt if pt else '',
            preexisting_quality_flag=str(sc.get('review_flagged') == 'True'),
            agent_elapsed_seconds=el if el is not None else '', agent_wall_hours=el / 3600 if el is not None else '',
            tool_calls=len(acts), chat_send_attempts=sum(a.get('canonical_tool') == 'chat_send' for a in acts),
            distinct_colleague_recipients_attempted=len(rec), agent_end_reason=st.get('agent_end_reason', '')))
    write_csv(cfg.data / 'runs.csv', out, FIELDS)
    print(json.dumps({'runs': len(out), 'model': cfg.model,
                      'flagged': [r['row'] for r in out if r['preexisting_quality_flag'] == 'True']}))


if __name__ == '__main__':
    main()
