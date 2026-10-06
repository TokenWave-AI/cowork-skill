"""Four-stage attribution of unresolved F2P nodes (discovery / ask / read / implement).

Inputs: per-node outcomes (node_outcomes/), node->requirement maps (req_map/),
requirement holders from the Oracle FULL_SPEC, and the frozen behaviour logs.
Rules, applied per requirement and taking the earliest stage over a node's requirements:
  discovery : the requirement's card never appears in any tool result returned to the agent,
              and (public requirements) no public task document carrying it was fetched;
  ask       : owner-held, card seen, but no committed disclosure of the fact to the agent;
  read      : disclosure committed but the reply body never returned in the transcript;
  implement : the fact reached the agent (owner disclosure visible, or public document read).
Nodes failed by grader infrastructure are excluded; nodes without a mapped requirement are 'unmapped'.

Adapted for cowork-model-report-skill: paths parametrised; rules unchanged. Writes OUT/data/ATTRIBUTION.csv.
"""
import csv, json, collections, re
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
ORDER = ['discovery', 'ask', 'read', 'implement']

nodes = collections.defaultdict(list)
for r in csv.DictReader(open(W / 'NODE_OUTCOMES.csv')):
    if r['node_class'] == 'f2p':
        nodes[r['row']].append(r)
disc = collections.defaultdict(dict)
for r in csv.DictReader(open(COMM / 'FACT_DISCLOSURES.csv')):
    disc[f"{int(r['row']):03d}"][r['fact_id']] = r

def tool_result_text(row):
    out = []
    for line in open(TRAJ / f'inputs/{row}/behavior/evidence.jsonl'):
        d = json.loads(line); rec = d.get('record', {})
        if rec.get('type') == 'user':
            out.append(json.dumps(rec.get('message', {}).get('content'), ensure_ascii=False))
    return '\n'.join(out)

def fetched_docs(row):
    keys = set()
    for line in open(TRAJ / f'inputs/{row}/behavior/actions.jsonl'):
        d = json.loads(line)
        s = json.dumps(d.get('input'), ensure_ascii=False)
        keys.update(re.findall(r'DOC-\d+', s))
    return keys

out = []
for row, ns in sorted(nodes.items()):
    mp = LINKS / f'{row}.json'
    if not mp.exists():
        continue
    m = json.load(open(mp))
    reqs = {r['req_id']: r for r in m['requirements']}
    spec = json.load(open(REL / f'oracle/{row}/FULL_SPEC.json'))
    pub_docs = {d.get('key') for d in (spec.get('public_task_documents') or []) if isinstance(d, dict)}
    text = tool_result_text(row)
    docs = fetched_docs(row)
    D = disc[row]
    def stage(rid):
        r = reqs.get(rid)
        if r is None:
            return None
        card = r.get('card_id')
        seen = bool(card) and card in text
        if r['holder'] == 'public':
            read_doc = bool(pub_docs & docs) or not pub_docs
            return 'implement' if (seen or read_doc) else 'discovery'
        d = D.get(rid)
        if d:
            return 'implement' if d['reply_body_visible_in_transcript'] == 'True' else 'read'
        return 'ask' if seen else 'discovery'
    for n in ns:
        if n['status'] != 'failed':
            continue
        if n['failure_class'] in ('infrastructure_or_blocked', 'timeout'):
            st = 'excluded_infrastructure'
        else:
            info = m['nodes'].get(n['node_id'], {})
            stages = [s for s in (stage(x) for x in info.get('req_ids', [])) if s]
            st = min(stages, key=ORDER.index) if stages else 'unmapped'
            holders = sorted({reqs[x]['holder'] != 'public' for x in info.get('req_ids', []) if x in reqs})
        out.append(dict(row=row, node_id=n['node_id'], failure_class=n['failure_class'], stage=st,
                        req_ids='|'.join(m['nodes'].get(n['node_id'], {}).get('req_ids', [])),
                        owner_held=any(reqs.get(x, {}).get('holder', 'public') != 'public'
                                       for x in m['nodes'].get(n['node_id'], {}).get('req_ids', [])),
                        confidence=m['nodes'].get(n['node_id'], {}).get('confidence', '')))
with open(W / 'ATTRIBUTION.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
c = collections.Counter(o['stage'] for o in out)
print(len({o['row'] for o in out}), 'rows', sum(c.values()), 'failed nodes', dict(c))
