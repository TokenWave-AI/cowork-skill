#!/usr/bin/env python3
"""Per-run context for the round-2 failure-diagnosis agents.

    OUT/diagnosis/context/NNN/
      CONTEXT.json       identity, outcome, every requirement with its nodes (status, failure class, grader
                         output), acquisition, questions naming the card, pipeline loss stage, delivery-note claim
                         (strict and broad, with excerpt), deferral threads, and failed P2P nodes
      SPEC.md            the task's complete specification from the bundle (oracle/NNN/FULL_SPEC.md)
      BLIND_REVIEW.json  the validated round-1 report, when present

Inputs: OUT/data (stages nodes, collab, basics), OUT/runs/NNN/NODES.csv (stage dossier, for grader output),
OUT/review/reviews/rows/NNN/report.json (stage review), the bundle, the package's requirement links.
"""
import collections
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import config, read_csv  # noqa: E402


def main():
    cfg = config(extra_args=lambda p: p.add_argument('--reviews', default=None))
    D = cfg.data
    reviews = Path(cfg.extra.get('reviews') or cfg.review / 'reviews')
    runs = {r['row']: r for r in read_csv(D / 'runs.csv')}
    rec = {r['row']: r for r in read_csv(D / 'RECONCILE.csv')}
    reqs = collections.defaultdict(list)
    for r in read_csv(D / 'requirements.csv'):
        reqs[r['row']].append(r)
    f2p = collections.defaultdict(list)
    for n in read_csv(D / 'f2p_nodes.csv'):
        f2p[n['row']].append(n)
    claims = {(r['row'], r['req_id']): r for r in read_csv(D / 'delivery_claims.csv')}
    broad = {(r['row'], r['req_id']): r for r in read_csv(D / 'delivery_claims_broad.csv')}
    defs = collections.defaultdict(list)
    for d in read_csv(D / 'deferrals.csv'):
        defs[d['row']].append(d)
    root = cfg.out / 'diagnosis' / 'context'
    root.mkdir(parents=True, exist_ok=True)
    made, skipped = 0, []
    for row, r in sorted(runs.items()):
        if rec.get(row, {}).get('match') != 'True':
            skipped.append(dict(row=row, reason='per-node outcomes not reconstructed'))
            continue
        dossier = cfg.out / 'runs' / row / 'NODES.csv'
        grader = {(n['node_class'], n['node_id']): n for n in read_csv(dossier)} if dossier.exists() else {}
        try:
            links = {x['req_id']: x for x in json.loads((cfg.links / f'{row}.json').read_text())['requirements']}
        except FileNotFoundError:
            skipped.append(dict(row=row, reason='no requirement links'))
            continue
        by_req = collections.defaultdict(list)
        for n in f2p[row]:
            for q in (n['req_ids'] or '').split(';'):
                if q:
                    by_req[q].append(n)
        out_reqs = []
        for q in reqs[row]:
            ns = by_req.get(q['req_id'], [])
            cl, cb = claims.get((row, q['req_id']), {}), broad.get((row, q['req_id']), {})
            out_reqs.append(dict(
                req_id=q['req_id'], card=q['card_id'] or None, topic=links.get(q['req_id'], {}).get('topic', ''),
                holder=q['holder'], acquisition=q['acquisition'],
                questions_naming_card=int(q['questions_naming_card'] or 0),
                nodes_total=len(ns), nodes_passed=sum(n['status'] == 'passed' for n in ns),
                pipeline_loss_stage=sorted({n['loss_stage'] for n in ns if n['loss_stage']}) or None,
                nodes=[dict(node_id=n['node_id'], status=n['status'], failure_class=n['failure_class'] or None,
                            ask_detail=n['ask_detail'] or None, mapping_confidence=n['mapping_confidence'],
                            grader_output=(grader.get(('f2p', n['node_id'])) or {}).get('grader_message') or None)
                       for n in ns],
                delivery_note=dict(strict=cl.get('claim_class'), broad=cb.get('claim_class'),
                                   listed_as_open=cl.get('listed_as_open'), match_method=cl.get('match_method'),
                                   excerpt=cl.get('evidence_snippet') or None, line=cl.get('evidence_line') or None),
                deferrals=[dict(recipient=d['recipient'], followed=d['followed'] == 'True', disclosed=d['disclosed'] == 'True',
                                budget_left_hours=float(d['budget_left_hours']), hours_until_run_end=float(d['hours_until_run_end']))
                           for d in defs[row] if d['card'] and d['card'] == q['card_id']]))
        p2p_failed = [dict(node_id=n['node_id'], failure_class=n['failure_class'] or None, grader_output=n['grader_message'] or None)
                      for (cls, _), n in grader.items() if cls == 'p2p' and n['status'] not in ('passed',)]
        ctx = dict(schema='cowork-diagnosis-context-v1',
                   identity=dict(row=row, task_id=r['task_id'], task_version=r['task_version'], run_id=r['run_id'],
                                 model=cfg.model),
                   outcome=dict(f2p_passed=int(r['f2p_passed']), f2p_total=int(r['f2p_total']),
                                p2p_passed=int(r['p2p_passed']), p2p_total=int(r['p2p_total']),
                                end_reason=r['agent_end_reason'], agent_hours=round(float(r['agent_wall_hours'] or 0), 3),
                                budget_hours=round(float(r['budget_seconds'] or 0) / 3600, 2)),
                   requirements=out_reqs, p2p_failed=p2p_failed,
                   notes=['pipeline_loss_stage is the mechanical earliest-stage rule (definitions.md); confirm or correct it.',
                          'grader_output is the verifier tail and may be terse or absent.',
                          'delivery_note.strict/broad are keyword-classifier readings; check the note itself.'])
        d = root / row
        d.mkdir(parents=True, exist_ok=True)
        (d / 'CONTEXT.json').write_text(json.dumps(ctx, ensure_ascii=False, indent=1) + '\n')
        spec = cfg.bundle / 'oracle' / row / 'FULL_SPEC.md'
        if spec.exists():
            shutil.copyfile(spec, d / 'SPEC.md')
        rj = reviews / 'rows' / row / 'report.json'
        st = reviews / 'rows' / row / 'STATUS.json'
        if rj.exists() and st.exists() and json.loads(st.read_text()).get('state') == 'complete':
            shutil.copyfile(rj, d / 'BLIND_REVIEW.json')
        elif (d / 'BLIND_REVIEW.json').exists():
            (d / 'BLIND_REVIEW.json').unlink()
        made += 1
    (root / 'SKIPPED.json').write_text(json.dumps(skipped, indent=1) + '\n')
    print(json.dumps({'contexts': made, 'skipped': skipped, 'dir': str(root)}))


if __name__ == '__main__':
    main()
