"""Per-run collaboration metrics joined to the Oracle owner-held requirement set.

Adapted for cowork-model-report-skill: paths parametrised; definitions unchanged.
Writes OUT/data/COLLAB_RUNS.csv and COLLAB_REQS.csv."""
import csv, json, re, collections, statistics as st
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
SNAP = W / 'runs.csv'
OUT = W
runs = {r['row']: r for r in csv.DictReader(open(SNAP))}

def owner_reqs(row):
    m = json.load(open(LINKS / f'{row}.json'))
    return {r['req_id']: dict(card=r.get('card_id'), owner=r['holder'], topic=r.get('topic'))
            for r in m['requirements'] if r['holder'] != 'public'}

def owner_reqs_spec(row):
    s = json.load(open(REL / f'oracle/{row}/FULL_SPEC.json'))
    oa = s.get('owner_answers')
    out = {}
    if isinstance(oa, list):
        for o in oa:
            for f in o.get('facts', []):
                out[f['iu']] = dict(card=f.get('card_id'), owner=o['owner'], topic=f.get('topic'))
    return out

asks = collections.defaultdict(list)
for l in open(COMM / 'ASK_CHAINS.jsonl'):
    d = json.loads(l); asks[f"{d['row']:03d}"].append(d)
disc = collections.defaultdict(dict)
for r in csv.DictReader(open(COMM / 'FACT_DISCLOSURES.csv')):
    disc[f"{int(r['row']):03d}"][r['fact_id']] = r
card_re = re.compile(r'\b[A-Z][A-Z0-9]{1,6}-\d{2,4}\b')

rows_out = []; req_out = []
for row in sorted(runs):
    R = owner_reqs(row)
    A = sorted(asks[row], key=lambda a: a['call_time'])
    D = disc[row]
    card_owner = {}
    for iu, v in R.items():
        if v['card']: card_owner[v['card']] = v['owner']
    # disclosure time per fact = call time of the ask that produced it
    ask_time = {a['action_id']: a['call_time'] for a in A}
    dtime = {iu: ask_time.get(r['action_id']) for iu, r in D.items()}
    # per-requirement status
    first_q = {}
    for a in A:
        for c in set(card_re.findall(a['question_text'] or '')):
            first_q.setdefault(c, a)
    n_asked = n_obt = n_vis = 0
    for iu, v in R.items():
        mention = [a for a in A if v['card'] and v['card'] in (a['question_text'] or '')]
        to_owner = [a for a in A if a['recipient_id'] == v['owner']]
        d = D.get(iu)
        asked = bool(d) or any(a['recipient_id'] == v['owner'] for a in mention)
        if d:
            stage = 'obtained' if d['reply_body_visible_in_transcript'] == 'True' else 'returned_not_visible'
        elif any(a['recipient_id'] == v['owner'] for a in mention):
            stage = 'asked_owner_about_card'
        elif mention:
            stage = 'asked_wrong_person_about_card'
        elif to_owner:
            stage = 'contacted_owner_not_card'
        else:
            stage = 'owner_never_contacted'
        n_asked += asked; n_obt += bool(d); n_vis += stage == 'obtained'
        req_out.append(dict(row=row, req_id=iu, card=v['card'], owner=v['owner'], stage=stage,
                            n_questions_on_card=len(mention), n_questions_to_owner=len(to_owner)))
    # targeting: first question about an owner-held card reaches its owner
    tgt = [first_q[c]['recipient_id'] == o for c, o in card_owner.items() if c in first_q]
    # redundancy: questions whose mentioned owner-held cards were all already obtained
    card_facts = collections.defaultdict(set)
    for iu, v in R.items(): card_facts[v['card']].add(iu)
    red = 0; red_den = 0
    for a in A:
        cs = [c for c in set(card_re.findall(a['question_text'] or '')) if c in card_facts]
        if not cs: continue
        red_den += 1
        if all(all(dtime.get(iu) is not None and dtime[iu] < a['call_time'] for iu in card_facts[c]) for c in cs):
            red += 1
    n_err = sum(a['return_status'] == 'explicit_is_error' for a in A)
    nR = len(R)
    rows_out.append(dict(
        row=row, f2p=float(runs[row]['f2p_rate']), owner_reqs=nR,
        ask_attempts=len(A),
        ask_rate=n_asked / nR if nR else None,
        obtained_rate=n_obt / nR if nR else None,
        visible_rate=n_vis / nR if nR else None,
        targeting=sum(tgt) / len(tgt) if tgt else None, targeting_n=len(tgt),
        gain_per_q=len(D) / len(A) if A else None,
        followthrough=(n_obt / n_asked) if n_asked else None,
        redundancy=red / red_den if red_den else None, redundancy_n=red_den,
        unread=(sum(1 for r in D.values() if r['reply_body_visible_in_transcript'] != 'True') / len(D)) if D else None,
        disclosed=len(D),
    ))
with open(OUT / 'COLLAB_RUNS.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows_out[0])); w.writeheader(); w.writerows(rows_out)
with open(OUT / 'COLLAB_REQS.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(req_out[0])); w.writeheader(); w.writerows(req_out)
print(collections.Counter(r['stage'] for r in req_out), len(req_out))
