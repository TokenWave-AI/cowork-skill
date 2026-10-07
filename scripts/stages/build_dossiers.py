#!/usr/bin/env python3
"""Per-run dossiers: everything recorded about each run, readable without the campaign.

The paper-level report aggregates; this stage keeps the detail so that whoever reads the report
never has to go back to the raw trajectories.  For every scored run it writes OUT/runs/NNN/:

  RUN.md            identity, outcome, effort/telemetry, tool usage, requirement-by-requirement table
                    (holder, acquisition, questions, nodes, loss stage, delivery-note claim), failed
                    nodes with grader output, deferral threads, sidecar event log, workplace checks,
                    reviewer judgement (if reviewed)
  conversation.md   every colleague exchange in time order: each question the agent sent (full text,
                    return status), each reply / notification it was shown (full text), and the
                    environment's own record of disclosures and deferrals
  transcript.md     the whole trajectory in order: assistant text and reasoning, every tool call
                    (input) and its result (complete by default; --dossier-result-chars N clips to head+tail), with run-time offsets
  SOLUTION.md       the delivery note as captured
  model.patch       the captured patch (+ PATCH_STAT.csv: per-file added/removed, test or production)
  review.md / review.json   the reviewer's full report, when the review stage has run

plus OUT/runs/INDEX.md and OUT/data/RUN_SUMMARY.csv (one wide row per run joining every per-run
table).  Read-only on the campaign; nothing here feeds statistics.json except RUN_SUMMARY.csv.
"""
import collections
import csv
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import config, read_csv, write_csv  # noqa: E402

TEST_PATH = re.compile(r'(^|/)(tests?|spec|specs|__tests__|testing|testdata|fixtures)(/|$)|'
                       r'(_test|_spec|\.test|\.spec|Test|Tests)\.[A-Za-z]+$|(^|/)test_[^/]+$')


def rk(x):
    return f'{int(x):03d}'


def by_row(rows, key='row'):
    d = collections.defaultdict(list)
    for r in rows:
        d[rk(r[key])].append(r)
    return d


def jsonl(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]


def hm(seconds):
    if seconds is None:
        return '–'
    sign, s = ('-' if seconds < 0 else ''), int(round(abs(seconds)))
    return f'{sign}{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}'


def clip(text, n):
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    if n <= 0 or len(text) <= n:
        return text
    h = n * 2 // 3
    return text[:h] + f'\n… [{len(text) - n} chars omitted] …\n' + text[-(n - h):]


def fence(text):
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, indent=1)
    ticks = '````' if '```' in text else '```'
    return f'{ticks}\n{text}\n{ticks}'


def cell(v, n=160):
    s = '' if v is None else str(v)
    s = s.replace('\n', ' ').replace('|', '\\|')
    return s if len(s) <= n else s[:n - 1] + '…'


def table(header, rows):
    out = ['| ' + ' | '.join(header) + ' |', '|' + '---|' * len(header)]
    out += ['| ' + ' | '.join(cell(c) for c in r) + ' |' for r in rows]
    return '\n'.join(out)


def result_text(content):
    """Flatten a tool_result content (str or list of blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                parts.append(b.get('text') if b.get('type') == 'text' else json.dumps(b, ensure_ascii=False)[:2000])
            else:
                parts.append(str(b))
        return '\n'.join(p for p in parts if p)
    return json.dumps(content, ensure_ascii=False)


def transcript(beh, t0, result_chars):
    """Markdown rendering of evidence.jsonl in physical order."""
    order = {}
    for a in jsonl(beh / 'actions.jsonl'):
        order[a['tool_use_id']] = (a['order'], a['canonical_tool'])
    lines = []
    for e in jsonl(beh / 'evidence.jsonl'):
        rec = e.get('record', {})
        t = e.get('observed_at')
        off = hm(t - t0) if (t and t0) else '–'
        kind = rec.get('type')
        content = (rec.get('message') or {}).get('content')
        if kind == 'system':
            sub = rec.get('subtype')
            if sub == 'init':
                lines.append(f'\n---\n**[{off}] session start** (attempt {e.get("attempt")}, init segment {e.get("init_segment")})')
            else:
                lines.append(f'\n**[{off}] system/{sub}** `{clip(json.dumps({k: v for k, v in rec.items() if k not in ("uuid", "session_id")}, ensure_ascii=False), 400)}`')
            continue
        if kind == 'result':
            lines.append(f'\n---\n**[{off}] run result** ({rec.get("subtype")}, turns {rec.get("num_turns")})\n\n' + fence(rec.get('result') or ''))
            continue
        if not isinstance(content, list):
            if content:
                lines.append(f'\n**[{off}] {kind}**\n\n' + fence(clip(content, result_chars)))
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            bt = b.get('type')
            if bt == 'thinking' and b.get('thinking'):
                lines.append(f'\n**[{off}] reasoning**\n\n' + '\n'.join('> ' + l for l in b['thinking'].strip().split('\n')))
            elif bt == 'text' and kind == 'assistant' and b.get('text'):
                lines.append(f'\n**[{off}] assistant**\n\n' + b['text'].strip())
            elif bt == 'text' and b.get('text'):
                lines.append(f'\n**[{off}] {kind} text**\n\n' + fence(clip(b['text'], result_chars)))
            elif bt == 'tool_use':
                o, tool = order.get(b.get('id'), ('?', b.get('name')))
                inp = b.get('input') or {}
                if isinstance(inp, dict) and set(inp) == {'command'}:
                    body = fence(inp['command'])
                else:
                    body = fence(json.dumps(inp, ensure_ascii=False, indent=1))
                lines.append(f'\n**[{off}] call #{o} `{tool}`**\n\n' + body)
            elif bt == 'tool_result':
                o, tool = order.get(b.get('tool_use_id'), ('?', ''))
                err = ' **(error)**' if b.get('is_error') else ''
                lines.append(f'\n[{off}] result #{o}{err}\n\n' + fence(clip(result_text(b.get('content')), result_chars)))
    return '\n'.join(lines) + '\n'


MSG_KEY = re.compile(r'(?i)tail|err|msg|message|output|detail|reason|trace|fail|assert|log')
_EVID = {}


def node_keys(nid):
    """Spellings of a node id across verifier formats: 'tests/x.py::test_unit[612]' == '612'."""
    keys = {nid}
    m = re.search(r'\[([^\]]+)\]$', nid)
    if m:
        keys.add(m.group(1))
    m = re.match(r'(?i)^pr[-_ ]?(\d+)$', nid)
    if m:
        keys.add(m.group(1))
    for k in list(keys):
        keys.update({f'[f2p] {k}', f'[p2p] {k}'})
    return keys


def grader_output(n, limit=2000):
    """Raw grader output for one failed node, read from the verifier evidence file the node stage chose,
    plus lines naming the node in sibling text logs of the same verifier directory."""
    path = n['evidence_path']
    if path not in _EVID:
        try:
            if path.endswith('.jsonl'):
                _EVID[path] = [json.loads(l) for l in open(path, errors='ignore') if l.strip()]
            elif path.endswith('.json'):
                _EVID[path] = json.load(open(path, errors='ignore'))
            else:
                _EVID[path] = open(path, errors='ignore').read()
        except (OSError, ValueError):
            _EVID[path] = None
    data, keys = _EVID[path], node_keys(n['node_id'])
    found = []

    def text_hits(text):
        pat = re.compile('|'.join(r'(?<![\w-])' + re.escape(k) + r'(?![\w-])' for k in keys))
        return [l for l in text.split('\n') if pat.search(l)]

    def summarise(o):
        parts = [f'{k}: {v.strip()}' for k, v in o.items() if isinstance(v, str) and v.strip() and MSG_KEY.search(k)]
        if not parts:
            parts = [json.dumps({k: v for k, v in o.items() if not isinstance(v, (dict, list)) or k == 'command'},
                                ensure_ascii=False)]
        return '\n'.join(parts)

    def walk(o, depth=0):
        if depth > 12 or len(found) > 3:
            return
        if isinstance(o, dict):
            if any(isinstance(v, (str, int)) and not isinstance(v, bool) and str(v) in keys for v in o.values()):
                found.append(summarise(o))
                log = (o.get('extra') or {}).get('log') if isinstance(o.get('extra'), dict) else None
                if isinstance(log, str) and (Path(path).parent / log).is_file():
                    found.append(f'[{log}]\n' + clip((Path(path).parent / log).read_text(errors='ignore'), 1200))
            for k, v in o.items():
                if str(k) in keys and isinstance(v, dict):
                    found.append(summarise(v))
                walk(v, depth + 1)
        elif isinstance(o, list):
            for v in o:
                walk(v, depth + 1)
    if isinstance(data, str):
        found.append('\n'.join(text_hits(data)[-20:]))
    elif data is not None:
        walk(data)
    vdir = Path(path).parent
    for log in sorted(vdir.glob('*.log')) + sorted(vdir.parent.glob('*.log')):
        if str(log) == path or log.stat().st_size > 20e6:
            continue
        key = str(log)
        if key not in _EVID:
            _EVID[key] = log.read_text(errors='ignore')
        hits = text_hits(_EVID[key])
        if hits:
            found.append(f'[{log.name}]\n' + '\n'.join(hits[-12:]))
    return clip('\n'.join(x for x in found if x), limit)


def patch_stat(patch):
    rows = []
    for chunk in re.split(r'(?=^diff --git )', patch, flags=re.M):
        m = re.match(r'diff --git a/(\S+) b/(\S+)', chunk)
        if not m:
            continue
        path = m.group(2)
        added = sum(1 for l in chunk.split('\n') if l.startswith('+') and not l.startswith('+++'))
        removed = sum(1 for l in chunk.split('\n') if l.startswith('-') and not l.startswith('---'))
        head = chunk[:400]
        status = 'added' if 'new file mode' in head else 'deleted' if 'deleted file mode' in head else 'modified'
        rows.append(dict(path=path, kind='test' if TEST_PATH.search(path) else 'other', status=status,
                         added=added, removed=removed))
    return rows


def main():
    cfg = config(extra_args=lambda p: p.add_argument('--dossier-result-chars', type=int, default=0))
    result_chars = cfg.extra.get('dossier_result_chars')
    result_chars = 0 if result_chars is None else int(result_chars)
    D, C = cfg.data, cfg.comm
    runs = {r['row']: r for r in read_csv(D / 'runs.csv')}
    tel = {rk(r['row']): r for r in read_csv(cfg.telemetry / 'RUN_TELEMETRY.csv')}
    tools = by_row(read_csv(cfg.telemetry / 'TOOL_BREAKDOWN.csv'))
    collab = {r['row']: r for r in read_csv(D / 'collaboration_runs.csv')}
    wp = {r['row']: r for r in read_csv(D / 'workplace_basics_runs.csv')}
    stop = {r['row']: r for r in read_csv(D / 'stopping.csv')} if (D / 'stopping.csv').exists() else {}
    rec = {r['row']: r for r in read_csv(D / 'RECONCILE.csv')}
    reqs = by_row(read_csv(D / 'requirements.csv'))
    nodes = by_row(read_csv(D / 'f2p_nodes.csv'))
    allnodes = by_row(read_csv(D / 'NODE_OUTCOMES.csv'))
    claims = {(r['row'], r['req_id']): r for r in read_csv(D / 'delivery_claims.csv')}
    broad = {(r['row'], r['req_id']): r for r in read_csv(D / 'delivery_claims_broad.csv')}
    defs = by_row(read_csv(D / 'deferrals.csv'))
    asks = by_row(jsonl(C / 'ASK_CHAINS.jsonl'))
    disc = by_row(read_csv(C / 'FACT_DISCLOSURES.csv'))
    avail = by_row(read_csv(C / 'AVAILABILITY_EVENTS.csv'))
    notes = by_row(read_csv(C / 'NOTIFICATION_CHAINS.csv'))
    qdec = json.loads((D / 'question_deciles.json').read_text()).get('first_edit_fraction', {})
    rsum = cfg.review / 'summary'
    rev_rows = {rk(r['row']): r for r in read_csv(rsum / 'STOP_ASSESSMENTS.csv')} if (rsum / 'STOP_ASSESSMENTS.csv').exists() else {}
    dims = by_row(read_csv(rsum / 'DIMENSIONS.csv')) if (rsum / 'DIMENSIONS.csv').exists() else {}
    tasks = {}
    if cfg.release_tasks.exists():
        tasks = {rk(t['row']): t for t in json.loads(cfg.release_tasks.read_text())}

    root = cfg.out / 'runs'
    root.mkdir(parents=True, exist_ok=True)
    summary, index = [], []
    for row in sorted(runs):
        r = runs[row]
        d = root / row
        d.mkdir(exist_ok=True)
        beh = cfg.inputs / row / 'behavior'
        acts = jsonl(beh / 'actions.jsonl')
        t0 = acts[0]['call_time'] if acts and acts[0].get('call_time') else None
        try:
            links = {x['req_id']: x for x in json.loads((cfg.links / f'{row}.json').read_text())['requirements']}
        except FileNotFoundError:
            links = {}
        task = tasks.get(row, {})
        te = tel.get(row, {})
        co = collab.get(row, {})
        w = wp.get(row, {})
        sp = stop.get(row, {})
        rc = rec.get(row, {})

        # ---- requirements -------------------------------------------------------------------
        node_by_req = collections.defaultdict(list)
        for n in nodes.get(row, []):
            for q in (n['req_ids'] or '').split(';'):
                if q:
                    node_by_req[q].append(n)
        defs_by_card = collections.defaultdict(list)
        for x in defs.get(row, []):
            defs_by_card[x['card']].append(x)
        req_rows = []
        for q in reqs.get(row, []):
            ns = node_by_req.get(q['req_id'], [])
            passed = sum(1 for n in ns if n['status'] == 'passed')
            stages = collections.Counter(n['loss_stage'] for n in ns if n['loss_stage'])
            cl = claims.get((row, q['req_id']), {})
            cb = broad.get((row, q['req_id']), {})
            dfs = defs_by_card.get(q['card_id'], [])
            req_rows.append(dict(
                req_id=q['req_id'], card=q['card_id'], topic=links.get(q['req_id'], {}).get('topic', ''),
                holder=q['holder'], acquisition=q['acquisition'], questions_naming_card=q['questions_naming_card'],
                nodes=len(ns), passed=passed, loss=','.join(f'{k}:{v}' for k, v in stages.items()),
                claim=cl.get('claim_class', ''), claim_broad=cb.get('claim_class', ''),
                deferral=('abandoned' if any(x['followed'] == 'False' for x in dfs) else 'followed') if dfs else '',
                note_excerpt=cl.get('evidence_snippet', '')))
        write_csv(d / 'REQUIREMENTS.csv', req_rows)

        # ---- nodes ----------------------------------------------------------------------------
        f2p_meta = {n['node_id']: n for n in nodes.get(row, [])}
        node_rows = []
        for n in allnodes.get(row, []):
            m = f2p_meta.get(n['node_id'], {}) if n['node_class'] == 'f2p' else {}
            node_rows.append(dict(node_class=n['node_class'], node_id=n['node_id'], status=n['status'],
                                  failure_class=n['failure_class'], req_ids=m.get('req_ids', ''),
                                  information_state=m.get('information_state', ''), loss_stage=m.get('loss_stage', ''),
                                  ask_detail=m.get('ask_detail', ''),
                                  grader_message=grader_output(n) if n['status'] not in ('passed', 'unresolved') else ''))
        write_csv(d / 'NODES.csv', node_rows)

        # ---- patch / note ---------------------------------------------------------------------
        sub = beh / 'submission'
        pstat = []
        for name in ('SOLUTION.md', 'model.patch'):
            if (sub / name).exists():
                shutil.copyfile(sub / name, d / name)
        if (sub / 'model.patch').exists():
            pstat = patch_stat((sub / 'model.patch').read_text(errors='ignore'))
            write_csv(d / 'PATCH_STAT.csv', pstat, ['path', 'kind', 'status', 'added', 'removed'])

        # ---- review ---------------------------------------------------------------------------
        rv = rev_rows.get(row)
        review = None
        if rv and rv.get('report'):
            rmd = Path(rv['report'])
            if rmd.exists():
                shutil.copyfile(rmd, d / 'review.md')
            rj = rmd.with_name('report.json')
            if rj.exists():
                shutil.copyfile(rj, d / 'review.json')
                review = json.loads(rj.read_text())

        dg = cfg.out / 'diagnosis' / 'rows' / row
        if (dg / 'report.md').exists() and (dg / 'STATUS.json').exists() and \
                json.loads((dg / 'STATUS.json').read_text()).get('state') == 'complete':
            shutil.copyfile(dg / 'report.md', d / 'diagnosis.md')
            shutil.copyfile(dg / 'report.json', d / 'diagnosis.json')

        # ---- conversation.md ------------------------------------------------------------------
        ev_by_line = {}
        if beh.exists():
            for i, e in enumerate(jsonl(beh / 'evidence.jsonl'), 1):
                ev_by_line[e['event_id']] = e
        items = []
        for a in acts:
            if a['canonical_tool'] != 'chat_send':
                continue
            inp = a.get('input') or {}
            res = a['results'][0] if a.get('results') else {}
            status = 'error' if res.get('is_error') else ('no return' if not res else 'sent')
            rtxt = ''
            if res.get('is_error'):
                er = ev_by_line.get(res['evidence']['event_id'], {}).get('record', {})
                for b in (er.get('message') or {}).get('content', []) or []:
                    if isinstance(b, dict) and b.get('type') == 'tool_result':
                        rtxt = result_text(b.get('content'))
            items.append((a.get('call_time') or 0, 0,
                          f"### [{hm((a['call_time'] - t0) if t0 and a.get('call_time') else None)}] → {inp.get('recipient_id') or inp.get('conversation') or '?'}  (call #{a['order']}, {status})\n\n"
                          + fence(inp.get('text') or json.dumps(inp, ensure_ascii=False))
                          + (('\n\nReturned:\n\n' + fence(clip(rtxt, 1500))) if rtxt else '')))
        seen = set()
        for x in jsonl(beh / 'message_exposures.jsonl'):
            m = x.get('message') or {}
            mid = m.get('id') or x.get('message_id')
            if mid in seen or str(mid).startswith('runtime-question'):
                continue
            seen.add(mid)
            act_t = next((a['call_time'] for a in acts if a['action_id'] == x.get('action_id')), None)
            kind = 'reply' if 'answer' in str(mid) else 'notification' if re.match(r'runtime-D\d', str(mid)) else 'message'
            items.append((act_t or 0, 1,
                          f"### [{hm((act_t - t0) if act_t and t0 else None)}] ← {m.get('author_id')} {m.get('author') or ''}  ({kind} {mid}, first shown by {x.get('action_id')}, thread {m.get('thread_id')}, source time {m.get('at')})\n\n"
                          + fence(m.get('text') or '')))
        sc_lines = []
        for x in jsonl(beh / 'sidecar.jsonl'):
            s = x.get('record', {})
            keep = {k: s.get(k) for k in ('event', 'at', 'recipient_id', 'card_id', 'fact_id', 'fact_ids', 'question_message_id',
                                          'reply_message_id', 'first_defer', 'required_followups', 'qualified_followups',
                                          'delivery_id', 'transaction_committed') if s.get(k) not in (None, '', [])}
            sc_lines.append(keep)
        conv = [f'# Row {row} — colleague communication\n',
                f'{len([i for i in items if i[1] == 0])} messages sent, {len(seen)} distinct replies/notifications shown. '
                'Times (h:mm:ss) are offsets from the run\'s first tool call (the origin used by the deferral and question-timing analyses) to the call that sent or first returned the message. '
                'Static workplace chat history read via chat_fetch is in transcript.md.\n',
                '## Exchanges\n'] + [i[2] + '\n' for i in sorted(items, key=lambda i: (i[0], i[1]))]
        conv += ['## Environment record: disclosures\n',
                 table(['fact', 'card', 'recipient', 'question', 'reply', 'committed', 'reply shown to agent', 'at'],
                       [[x['fact_id'], x['card_id'], x['recipient_id'], x['question_id'], x['reply_id'],
                         x['transaction_committed'], x['reply_body_visible_in_transcript'], x['sidecar_at']] for x in disc.get(row, [])]) + '\n',
                 '## Environment record: availability / deferral events\n',
                 table(['event', 'recipient', 'card', 'question', 'reply', 'first defer', 'required follow-ups', 'qualified follow-ups', 'at'],
                       [[x['event'], x['recipient_id'], x['card_id'], x['question_id'], x['reply_id'], x['first_defer'],
                         x['required_followups'], x['qualified_followups'], x['sidecar_at']] for x in avail.get(row, [])]) + '\n',
                 '## Environment record: notifications released\n',
                 table(['message', 'delivery', 'times shown', 'cards named', 'later actions naming the card'],
                       [[x['message_id'], x['delivery_id_from_message_format'], x['visible_return_occurrences'],
                         x.get('card_tokens', ''), x.get('literal_card_candidate_action_count', '')] for x in notes.get(row, [])]) + '\n',
                 '## Sidecar event log (all events, in order)\n',
                 table(['#', 'event', 'details'], [[i + 1, s.get('event', ''), json.dumps({k: v for k, v in s.items() if k != 'event'}, ensure_ascii=False)]
                                                  for i, s in enumerate(sc_lines)]) + '\n']
        (d / 'conversation.md').write_text('\n'.join(conv))

        # ---- transcript.md --------------------------------------------------------------------
        if (beh / 'evidence.jsonl').exists():
            (d / 'transcript.md').write_text(f'# Row {row} — full trajectory\n\nTimes are offsets from the first tool call. ' +
                                             (f'Tool results are clipped to {result_chars} characters (head and tail kept).\n' if result_chars else 'Tool results are complete.\n') + transcript(beh, t0, result_chars))

        # ---- RUN.md ---------------------------------------------------------------------------
        f2p_fail = [n for n in node_rows if n['node_class'] == 'f2p' and n['status'] != 'passed']
        p2p_fail = [n for n in node_rows if n['node_class'] == 'p2p' and n['status'] != 'passed']
        acq = collections.Counter(x['acquisition'] for x in req_rows if x['holder'] != 'public' and x['acquisition'] != 'public')
        stage_ct = collections.Counter(n['loss_stage'] for n in f2p_fail if n['loss_stage'])
        claim_ct = collections.Counter(x['claim'] for x in req_rows if x['claim'])
        n_def = len(defs.get(row, []))
        n_ab = sum(1 for x in defs.get(row, []) if x['followed'] == 'False')
        test_edit = sum(1 for p in pstat if p['kind'] == 'test' and p['status'] != 'added' and p['removed'])
        md = [f'# Row {row} — {r["task_id"]}\n',
              table(['field', 'value'], [
                  ['run_id', r['run_id']], ['task version', r['task_version']],
                  ['repo / language / domain', f"{task.get('repo', '')} / {task.get('language', '')} / {task.get('domain', '')}"],
                  ['model / effort', f"{r['solver_model_requested']} / {r['solver_effort_requested']}"],
                  ['scaffold', f"{r['scaffold']} {r['scaffold_version']}"], ['colleague model', r['colleague_model_requested']],
                  ['budget', hm(float(r['budget_seconds'] or 0))], ['agent time used', hm(float(r['agent_elapsed_seconds'] or 0))],
                  ['end reason', r['agent_end_reason']],
                  ['F2P', f"{r['f2p_passed']}/{r['f2p_total']}"], ['P2P', f"{r['p2p_passed']}/{r['p2p_total']}"],
                  ['pre-existing quality flag', r['preexisting_quality_flag']],
                  ['per-node reconciliation', f"{rc.get('match', '')} ({rc.get('method', '')}) {rc.get('notes', '')}"],
                  ['tool calls (errors)', f"{te.get('tool_calls', '')} ({te.get('tool_error_calls', '')})"],
                  ['colleague messages / distinct colleagues', f"{r['chat_send_attempts']} / {r['distinct_colleague_recipients_attempted']}"],
                  ['attempts / API retries', f"{te.get('attempt_count', '')} / {te.get('api_retry_count_reported', '')}"],
                  ['solver tokens observed (input / cache read / cache write / output)',
                   f"{te.get('solver_observed_message_input_tokens', '')} / {te.get('solver_observed_message_cache_read_input_tokens', '')} / "
                   f"{te.get('solver_observed_message_cache_creation_input_tokens', '')} / {te.get('solver_observed_message_output_tokens', '')}"],
                  ['colleague tokens observed (total)', te.get('colleague_observed_phase_total_tokens', '')],
                  ['first code edit at (fraction of run)', qdec.get(row, '')],
                  ['delivery note', f"{w.get('delivery_note_bytes', '')} bytes; brief asked for one: {w.get('told_delivery_note', '')}"],
                  ['patch', f"{len(pstat)} files, +{sum(p['added'] for p in pstat)} / -{sum(p['removed'] for p in pstat)}; "
                            f"existing test files changed: {w.get('existing_test_files_edited', '')} "
                            f"(lines removed {w.get('existing_test_lines_removed', '')}; brief forbids: {w.get('test_rule', '')})"],
                  ['stop judgement (reviewer)', f"{sp.get('premature_stop', '–')} ({sp.get('ending_type', '–')}, {sp.get('known_unresolved_items', '–')} known unresolved)"],
              ]) + '\n',
              '## Collaboration\n',
              table(['colleague-held reqs', 'obtained', 'card raised, not disclosed', 'owner contacted, card not raised', 'owner never contacted',
                     'ask rate', 'targeting', 'gain/Q', 'follow-through', 'redundancy', 'unread', 'deferral threads (abandoned)'],
                    [[sum(acq.values()), acq.get('obtained', 0) + acq.get('returned_not_visible', 0), acq.get('asked_owner_about_card', 0) + acq.get('asked_wrong_person_about_card', 0),
                      acq.get('contacted_owner_not_card', 0), acq.get('owner_never_contacted', 0),
                      co.get('ask_rate', ''), co.get('targeting', ''), co.get('gain_per_q', ''), co.get('followthrough', ''),
                      co.get('redundancy', ''), co.get('unread', ''), f'{n_def} ({n_ab})']]) + '\n',
              f'Failed F2P nodes by loss stage: {dict(stage_ct) or "none"}. Delivery-note claims (strict): {dict(claim_ct)}.\n',
              '## Requirements (one row per requirement; `REQUIREMENTS.csv` has the same table)\n',
              table(['req', 'card', 'topic', 'holder', 'acquisition', 'Qs naming card', 'nodes', 'passed', 'loss stage',
                     'note said (strict/broad)', 'deferral', 'note excerpt'],
                    [[x['req_id'], x['card'], x['topic'], x['holder'], x['acquisition'], x['questions_naming_card'], x['nodes'],
                      x['passed'], x['loss'], f"{x['claim']}/{x['claim_broad']}", x['deferral'], x['note_excerpt']] for x in req_rows]) + '\n',
              f'## Failed nodes ({len(f2p_fail)} F2P, {len(p2p_fail)} P2P; `NODES.csv` lists all nodes)\n',
              table(['class', 'node', 'requirement', 'information state', 'loss stage', 'failure class', 'grader output (tail)'],
                    [[n['node_class'], n['node_id'], n['req_ids'], n['information_state'], n['loss_stage'] + (f" ({n['ask_detail']})" if n['ask_detail'] else ''),
                      n['failure_class'], cell(n['grader_message'], 300)] for n in f2p_fail + p2p_fail]) + '\n',
              '## Deferral threads\n',
              table(['colleague', 'card', 'followed up', 'disclosed', 'budget left (h)', 'run continued (h)', 'requirement', 'nodes passed'],
                    [[x['recipient'], x['card'], x['followed'], x['disclosed'], x['budget_left_hours'], x['hours_until_run_end'],
                      x['req_id'], f"{x['passed']}/{x['nodes']}"] for x in defs.get(row, [])]) + '\n',
              '## Questions sent\n',
              table(['#', 'at', 'to', 'return', 'facts disclosed', 'question (start)'],
                    [[a['order'], hm(a['call_time'] - t0) if t0 and a.get('call_time') else '–', a['recipient_id'], a['return_status'],
                      ','.join(a.get('declared_fact_ids') or []), cell(a['question_text'], 200)] for a in asks.get(row, [])]) + '\n',
              '## Tool usage\n',
              table(['tool', 'calls', 'errors', 'repeated identical calls', 'distinct entities returned'],
                    [[t['tool'], t['calls'], t['error_calls'], t['identical_call_repeat_occurrences'], t['unique_returned_entities']]
                     for t in sorted(tools.get(row, []), key=lambda t: -int(t['calls']))]) + '\n',
              '## Patch by file\n',
              table(['file', 'kind', 'status', '+', '-'], [[p['path'], p['kind'], p['status'], p['added'], p['removed']] for p in pstat]) + '\n']
        if review:
            s = review.get('summary', {})
            md += ['## Reviewer judgement (LLM rubric review; full text in review.md)\n',
                   s.get('overall_assessment', '') + '\n', '**Strategy profile.** ' + s.get('strategy_profile', '') + '\n',
                   '**Strengths**\n' + '\n'.join('- ' + x for x in s.get('strengths', [])) + '\n',
                   '**Weaknesses**\n' + '\n'.join('- ' + x for x in s.get('weaknesses', [])) + '\n',
                   table(['dimension', 'score', 'status', 'confidence', 'assessment'],
                         [[x['dimension'], x['score'], x['observation_status'], x['confidence'], cell(x['assessment'], 400)] for x in dims.get(row, [])]) + '\n']
            sa = review.get('stop_assessment') or {}
            if sa:
                md += ['**Stop assessment.** ' + f"{sa.get('ending_type')} / premature: {sa.get('premature_stop')}. " + (sa.get('reason') or '') + '\n',
                       'Known unresolved items:\n' + '\n'.join('- ' + x for x in sa.get('known_unresolved_items') or []) + '\n']
            if review.get('quality_flags'):
                md += ['**Quality flags**\n', table(['category', 'severity', 'description'],
                                                    [[q['category'], q['severity'], cell(q['description'], 400)] for q in review['quality_flags']]) + '\n']
        md += ['## Files in this directory\n',
               '`conversation.md` all colleague exchanges · `transcript.md` the full trajectory · `REQUIREMENTS.csv` · `NODES.csv` · '
               '`SOLUTION.md` delivery note · `model.patch` + `PATCH_STAT.csv` · `review.md`/`review.json` round-1 report · '
               '`diagnosis.md`/`diagnosis.json` round-2 failure diagnosis.\n']
        (d / 'RUN.md').write_text('\n'.join(md))

        srow = dict(row=row, task_id=r['task_id'], repo=task.get('repo', ''), language=task.get('language', ''),
                    domain=task.get('domain', ''), f2p_passed=r['f2p_passed'], f2p_total=r['f2p_total'],
                    p2p_passed=r['p2p_passed'], p2p_total=r['p2p_total'],
                    strict=r['f2p_passed'] == r['f2p_total'] and r['p2p_passed'] == r['p2p_total'],
                    end_reason=r['agent_end_reason'], agent_hours=round(float(r['agent_wall_hours'] or 0), 3),
                    tool_calls=r['tool_calls'], tool_error_calls=te.get('tool_error_calls', ''),
                    attempts=te.get('attempt_count', ''), api_retries=te.get('api_retry_count_reported', ''),
                    solver_output_tokens_observed=te.get('solver_observed_message_output_tokens', ''),
                    solver_cache_read_tokens_observed=te.get('solver_observed_message_cache_read_input_tokens', ''),
                    colleague_tokens_observed=te.get('colleague_observed_phase_total_tokens', ''),
                    messages=r['chat_send_attempts'], colleagues=r['distinct_colleague_recipients_attempted'],
                    colleague_held=sum(acq.values()), obtained=acq.get('obtained', 0) + acq.get('returned_not_visible', 0),
                    card_raised_not_disclosed=acq.get('asked_owner_about_card', 0) + acq.get('asked_wrong_person_about_card', 0),
                    owner_contacted_card_not_raised=acq.get('contacted_owner_not_card', 0),
                    owner_never_contacted=acq.get('owner_never_contacted', 0),
                    **{f'lost_{k}': stage_ct.get(k, 0) for k in ('discovery', 'ask', 'read', 'implement')},
                    f2p_failed=len(f2p_fail), p2p_failed=len(p2p_fail),
                    ask_rate=co.get('ask_rate', ''), targeting=co.get('targeting', ''), gain_per_q=co.get('gain_per_q', ''),
                    followthrough=co.get('followthrough', ''), redundancy=co.get('redundancy', ''), unread=co.get('unread', ''),
                    deferral_threads=n_def, deferrals_abandoned=n_ab,
                    claimed_done=claim_ct.get('claimed_done', 0),
                    claimed_done_failed=sum(1 for x in req_rows if x['claim'] == 'claimed_done' and x['nodes'] and x['passed'] < x['nodes']),
                    listed_open=claim_ct.get('claimed_partial_or_open', 0), not_mentioned=claim_ct.get('not_mentioned', 0),
                    first_edit_fraction=qdec.get(row, ''), delivery_note_bytes=w.get('delivery_note_bytes', ''),
                    patch_files=len(pstat), patch_added=sum(p['added'] for p in pstat), patch_removed=sum(p['removed'] for p in pstat),
                    existing_test_files_edited=w.get('existing_test_files_edited', ''), test_rule=w.get('test_rule', ''),
                    stop_label=sp.get('premature_stop', ''), ending_type=sp.get('ending_type', ''),
                    known_unresolved_items=sp.get('known_unresolved_items', ''), reconciled=rc.get('match', ''))
        summary.append(srow)
        index.append([f'[{row}]({row}/RUN.md)', r['task_id'], f"{r['f2p_passed']}/{r['f2p_total']}", f"{r['p2p_passed']}/{r['p2p_total']}",
                      r['agent_end_reason'], f"{float(r['agent_wall_hours'] or 0):.1f}", r['chat_send_attempts'],
                      f"{srow['obtained']}/{srow['colleague_held']}", ' '.join(f'{k[0].upper()}{v}' for k, v in stage_ct.items()),
                      f"{n_ab}/{n_def}", f"{srow['claimed_done_failed']}/{srow['claimed_done']}", sp.get('premature_stop', '–')])
    write_csv(D / 'RUN_SUMMARY.csv', summary)
    (root / 'INDEX.md').write_text(
        f'# {cfg.model}: per-run dossiers\n\nLoss stages: D discovery, A ask, R read, I implement. '
        'Deferrals: abandoned/threads. Claims: reported done but failing / reported done (strict).\n\n' +
        table(['row', 'task', 'F2P', 'P2P', 'end', 'hours', 'msgs', 'obtained', 'lost at', 'deferrals', 'claims', 'premature stop'], index) + '\n')
    print(json.dumps({'dossiers': len(summary), 'dir': str(root)}))


if __name__ == '__main__':
    main()
