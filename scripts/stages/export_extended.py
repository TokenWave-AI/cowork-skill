"""Freeze the extended observed-run analysis into compact, path-free CSVs.

Adapted for cowork-model-report-skill: writes OUT/data/{requirements,f2p_nodes,collaboration_runs}.csv;
stopping.csv is written by the review stage (it needs validated rubric reviews)."""
import csv, json, glob, collections
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import config  # noqa: E402
_CFG = config()
REL = _CFG.bundle
TRAJ = _CFG.campaign            # campaign root: inputs/<row>/behavior
COMM = _CFG.comm                # extracted communication tables (this report's telemetry stage)
LINKS = _CFG.links              # package-level requirement_links/NNN.json (== paper work/req_map)
W = _CFG.data
OUT = W

def dump(name, rows):
    with open(OUT / name, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

runs_ = {r['row'] for r in csv.DictReader(open(W / 'runs.csv'))}
maps = {Path(p).stem: json.load(open(p)) for p in glob.glob(str(LINKS / '*.json')) if Path(p).stem in runs_}
reqs = {(r['row'], r['req_id']): r for r in csv.DictReader(open(W / 'COLLAB_REQS.csv'))}

# requirement-level status (owner-held only; public requirements are listed with holder=public)
rows = []
for row, m in sorted(maps.items()):
    for r in m['requirements']:
        k = (row, r['req_id'])
        rows.append(dict(row=row, req_id=r['req_id'], card_id=r.get('card_id') or '',
                         holder='public' if r['holder'] == 'public' else 'colleague',
                         acquisition=reqs[k]['stage'] if k in reqs else ('public' if r['holder'] == 'public' else 'unlinked'),
                         questions_naming_card=reqs[k]['n_questions_on_card'] if k in reqs else '',
                         f2p_nodes=len(r.get('nodes', []))))
dump('requirements.csv', rows)

# node-level outcome + requirement link + attribution
att = {(a['row'], a['node_id']): a for a in csv.DictReader(open(W / 'ATTRIBUTION.csv'))}
rows = []
for n in csv.DictReader(open(W / 'NODE_OUTCOMES.csv')):
    if n['node_class'] != 'f2p':
        continue
    m = maps.get(n['row'], {'nodes': {}, 'requirements': []})
    info = m['nodes'].get(n['node_id'], {})
    hold = {r['req_id']: r['holder'] for r in m['requirements']}
    ids = info.get('req_ids', [])
    if not ids:
        info_state = 'unmapped'
    elif all(hold.get(x) == 'public' for x in ids):
        info_state = 'public'
    else:
        st = [reqs[(n['row'], x)]['stage'] for x in ids if (n['row'], x) in reqs]
        info_state = 'colleague_obtained' if st and all(s == 'obtained' for s in st) else 'colleague_not_obtained'
    a = att.get((n['row'], n['node_id']), {})
    detail = ''
    if a.get('stage') == 'ask':
        st = [reqs[(n['row'], x)]['stage'] for x in ids if (n['row'], x) in reqs and reqs[(n['row'], x)]['stage'] != 'obtained']
        detail = 'card_raised' if any(s in ('asked_owner_about_card', 'asked_wrong_person_about_card') for s in st) else 'card_not_raised'
    rows.append(dict(row=n['row'], node_id=n['node_id'], status=n['status'],
                     failure_class=n['failure_class'], req_ids='|'.join(ids),
                     mapping_confidence=info.get('confidence', ''), information_state=info_state,
                     loss_stage=a.get('stage', ''), ask_detail=detail))
dump('f2p_nodes.csv', rows)

# per-run collaboration metrics
dump('collaboration_runs.csv', list(csv.DictReader(open(W / 'COLLAB_RUNS.csv'))))


print('exported', ['requirements.csv', 'f2p_nodes.csv', 'collaboration_runs.csv'])
