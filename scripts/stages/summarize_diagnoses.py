#!/usr/bin/env python3
"""Summarise validated round-2 failure diagnoses into tables the report and paper use.

Reads OUT/diagnosis/rows/NNN/{STATUS.json,report.json} (complete + re-validated only) and writes
OUT/diagnosis/summary/:
  DIAGNOSES.csv          one row per diagnosed requirement (stage, pipeline stage, mechanism, responsibility,
                         delivery-note verdict, counterfactual step, confidence)
  RUNS.csv               one row per run (headline, delivery-audit verdict, counts, case paragraph)
  FINDINGS.csv           workplace findings (title, novelty, requirements, description)
  REVISIONS.csv          round-1 judgements revised after seeing outcomes
  SUMMARY.json           counts: stage agreement matrix, mechanisms, responsibility, note verdicts, states
"""
import collections
import csv
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import config  # noqa: E402

SKILL = Path(__file__).resolve().parents[2] / 'skills' / 'cowork-failure-diagnosis'


def write(path, rows, fields):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def main():
    cfg = config()
    root = cfg.out / 'diagnosis'
    spec = importlib.util.spec_from_file_location('diag_validator', SKILL / 'scripts' / 'validate_diagnosis.py')
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    manifest = {int(r['row']): r for r in cfg.manifest()['rows']}
    out = root / 'summary'
    out.mkdir(parents=True, exist_ok=True)
    states = collections.Counter()
    diag, runs, findings, revisions, invalid = [], [], [], [], []
    for ctxdir in sorted((root / 'context').glob('[0-9][0-9][0-9]')):
        row = ctxdir.name
        d = root / 'rows' / row
        st = d / 'STATUS.json'
        if not st.exists():
            states['not_run'] += 1
            continue
        state = json.loads(st.read_text()).get('state')
        if state != 'complete':
            states[state] += 1
            continue
        rep = json.loads((d / 'report.json').read_text())
        errs = validator.validate(rep, manifest[int(row)]['input_dir'], ctxdir)
        if errs:
            states['invalidated'] += 1
            invalid.append(dict(row=row, errors=errs[:5]))
            continue
        states['complete'] += 1
        for r in rep['requirements']:
            diag.append(dict(row=row, req_id=r['req_id'], card=r['card'], holder=r['holder'],
                             nodes_failed=r['nodes_failed'], nodes_total=r['nodes_total'],
                             pipeline_stage=r['pipeline_stage'], stage=r['stage'], stage_agrees=r['stage_agrees'],
                             mechanism=r['mechanism'], agent_responsible=r['agent_responsible'],
                             note_verdict=r['delivery_note']['verdict'], confidence=r['confidence'],
                             what_was_needed=r['what_was_needed'], counterfactual_step=r['counterfactual_step'],
                             mechanism_note=r['mechanism_note'],
                             chain=' → '.join(f"[{s['phase']}] {s['description']}" for s in r['what_happened'])))
        a = rep['delivery_audit']
        runs.append(dict(row=row, task_id=rep['task']['task_id'], f2p=f"{rep['outcome']['f2p_passed']}/{rep['outcome']['f2p_total']}",
                         headline=rep['headline'], delivery_audit=a['verdict'], overstated=len(a['overstated_items']),
                         diagnosed=len(rep['requirements']), dominant_mechanism=rep['stage_summary']['dominant_mechanism'],
                         disagreements=len(rep['stage_summary']['disagreements_with_pipeline']),
                         findings=len(rep['workplace_findings']), revisions=len(rep['blind_review_revisions']),
                         case_paragraph=rep['case_paragraph'], report=str(d / 'report.md')))
        for f in rep['workplace_findings']:
            findings.append(dict(row=row, id=f['id'], novelty=f['novelty'], title=f['title'],
                                 req_ids=','.join(f['req_ids']), description=f['description']))
        for v in rep['blind_review_revisions']:
            revisions.append(dict(row=row, **{k: v[k] for k in ('dimension_or_field', 'round1', 'revision', 'reason')}))
    write(out / 'DIAGNOSES.csv', diag, ['row', 'req_id', 'card', 'holder', 'nodes_failed', 'nodes_total', 'pipeline_stage',
                                        'stage', 'stage_agrees', 'mechanism', 'agent_responsible', 'note_verdict',
                                        'confidence', 'what_was_needed', 'counterfactual_step', 'mechanism_note', 'chain'])
    write(out / 'RUNS.csv', runs, ['row', 'task_id', 'f2p', 'headline', 'delivery_audit', 'overstated', 'diagnosed',
                                   'dominant_mechanism', 'disagreements', 'findings', 'revisions', 'case_paragraph', 'report'])
    write(out / 'FINDINGS.csv', findings, ['row', 'id', 'novelty', 'title', 'req_ids', 'description'])
    write(out / 'REVISIONS.csv', revisions, ['row', 'dimension_or_field', 'round1', 'revision', 'reason'])
    C = collections.Counter
    summary = dict(
        states=dict(states), invalid=invalid, runs=len(runs), requirements=len(diag),
        stage=dict(C(x['stage'] for x in diag)), pipeline_stage=dict(C(x['pipeline_stage'] for x in diag)),
        stage_matrix={f"{p}->{s}": n for (p, s), n in C((x['pipeline_stage'], x['stage']) for x in diag).items()},
        stage_agreement=(sum(x['stage_agrees'] for x in diag) / len(diag)) if diag else None,
        mechanism=dict(C(x['mechanism'] for x in diag).most_common()),
        agent_responsible=dict(C(x['agent_responsible'] for x in diag)),
        note_verdict=dict(C(x['note_verdict'] for x in diag)),
        delivery_audit=dict(C(x['delivery_audit'] for x in runs)),
        findings_by_novelty=dict(C(x['novelty'] for x in findings)), revisions=len(revisions))
    (out / 'SUMMARY.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({k: summary[k] for k in ('states', 'runs', 'requirements', 'stage_agreement')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
