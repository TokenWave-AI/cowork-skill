#!/usr/bin/env python3
"""Build per-test-node outcome table for the graded runs of one model.

Adapted for cowork-model-report-skill (logic identical to the paper's build_node_outcomes.py):
expected counts come from OUT/data/runs.csv (built from each run's outcome.json score_snapshot),
the bundle and campaign are parameters, outputs go to OUT/data/.
Read-only on sources; writes NODE_OUTCOMES.csv and RECONCILE.csv.
Strategy: for each row choose the evidence directory that produced the selected score
(accepted-recovery-private when outcome.json score_snapshot.source says "accepted recovery"
and that dir has verifier logs; else raw-private), then try candidate per-node evidence files
(ctrf first, then other JSON/JSONL, then text logs) with a generic extractor; accept the
first candidate whose reconstructed f2p/p2p pass counts equal runs.csv exactly.
"""
import csv, glob, json, os, re, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import config  # noqa: E402
_CFG = config()
RUNS = str(_CFG.data / 'runs.csv')
BUNDLE = str(_CFG.bundle)
INPUTS = str(_CFG.inputs)
OUT = str(_CFG.data)

PASS_WORDS = {'passed', 'pass', 'ok', 'success', 'succeeded', 'true', 'green'}
FAIL_WORDS = {'failed', 'fail', 'failure', 'error', 'errored', 'false', 'blocked', 'skipped',
              'timeout', 'timed_out', 'missing', 'not_run', 'crashed', 'broken', 'infra_error',
              'compile_error', 'red', 'other', 'pending'}
FAIL_SUBSTR = ('fail', 'error', 'blocked', 'timeout', 'timed_out', 'skip', 'missing', 'invalid',
               'incomplete', 'not_run', 'crash', 'abort', 'broken', 'unsatisf')
ID_KEYS = ['node_id', 'nodeid', 'node', 'id', 'name', 'test', 'test_id', 'pr_number', 'pr', 'key', 'nodeId']
STATUS_KEYS = ['status', 'outcome', 'result', 'state', 'verdict', 'passed', 'ok', 'success', 'pass', 'category']
CLASS_KEYS = ['classification', 'failureKind', 'failure_reason_code', 'failure_class', 'failure_kind', 'category', 'kind_of_failure',
              'failure_category', 'error_class', 'failure_type', 'reason_code', 'class']


def load_tasks():
    m = json.load(open(os.path.join(BUNDLE, 'MANIFEST.json')))
    out = {}
    for t in m['tasks']:
        row = '%03d' % int(t['row'])
        cfg_p = os.path.join(BUNDLE, t['path'], 'tests', 'config.json')
        cfg = json.load(open(cfg_p)) if os.path.exists(cfg_p) else {}
        f2p = [str(x) for x in (cfg.get('f2p_node_ids') or t['f2p_nodes'])]
        p2p = [str(x) for x in (cfg.get('p2p_node_ids') or t.get('p2p_nodes') or [])]
        out[row] = dict(f2p=f2p, p2p=p2p, version=t['task_version'], grade=cfg.get('grade', {}),
                        aliases=config_aliases(cfg, set(f2p + p2p)))
    return out


def norm_status(v):
    if isinstance(v, bool):
        return 'passed' if v else 'failed'
    if isinstance(v, (int, float)):
        return None
    if isinstance(v, str):
        s = v.strip().lower()
        if s in PASS_WORDS:
            return 'passed'
        if s in FAIL_WORDS or any(w in s for w in FAIL_SUBSTR):
            return 'failed'
    return None


IDENT = re.compile(r'^[A-Za-z][A-Za-z0-9_\-]{2,60}$')
GENERIC = {'failed', 'fail', 'failure', 'error', 'false', 'f2p', 'p2p', 'passed', 'pass', 'true', 'ok'}


def get_class(d, status_word=None):
    """Best failure-class label: explicit class key > identifier-like reason > raw non-generic status."""
    if not isinstance(d, dict):
        return ''
    ex = d.get('extra')
    if isinstance(ex, dict):
        c = get_class(ex)
        if c:
            return c
    for k in CLASS_KEYS:
        v = d.get(k)
        if isinstance(v, str) and v and v.lower() not in GENERIC and IDENT.match(v):
            return v
    for k in ('reason', 'failure_reason', 'error_kind'):
        v = d.get(k)
        if isinstance(v, str) and IDENT.match(v) and v.lower() not in GENERIC:
            return v
    if isinstance(status_word, str) and status_word.lower() not in GENERIC and IDENT.match(status_word):
        return status_word
    return ''


MSG_KEYS = ('message', 'detail', 'reason', 'output_tail', 'tail', 'stderr', 'stdout', 'output', 'error', 'trace')


def get_msg(d):
    out = []
    if isinstance(d, dict):
        for k in MSG_KEYS:
            v = d.get(k)
            if isinstance(v, str):
                out.append(v[-4000:])
        for k in ('outcome', 'extra'):
            v = d.get(k)
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, dict):
                out.append(get_msg(v))
    return '\n'.join(out)


def walk_records(obj, path=()):
    """Yield (id_candidate, status, failure_class, bucket_hint) from arbitrary JSON."""
    if isinstance(obj, dict):
        # record style: has id key and status key
        st = None
        sw = None
        for sk in STATUS_KEYS:
            if sk in obj:
                st = norm_status(obj[sk])
                if st:
                    sw = obj[sk]
                    break
        if st:
            ids = []
            for ik in ID_KEYS:
                v = obj.get(ik)
                if isinstance(v, (str, int)) and not isinstance(v, bool):
                    ids.append(str(v))
            if ids:
                hint = obj.get('bucket') or obj.get('kind') or obj.get('node_class') or obj.get('type') or obj.get('suite')
                yield ids, st, (get_class(obj, sw), get_msg(obj)), (hint if isinstance(hint, str) else (path[-1] if path else ''))
        # mapping style: key -> bool/status str/dict-with-status
        for k, v in obj.items():
            hint = path[-1] if path else ''
            lk = str(k).lower()
            if isinstance(v, list) and v and all(isinstance(x, str) for x in v) and \
                    re.match(r'^(f2p|p2p|nodes?)?_?(passed|failed|pass|fail|errors?|blocked)$', lk):
                st = 'passed' if 'pass' in lk else 'failed'
                for x in v:
                    yield [x], st, ('' if st == 'passed' else lk, ''), hint
                continue
            if isinstance(v, (bool, str)):
                s = norm_status(v)
                if s and k not in STATUS_KEYS and k not in ID_KEYS and k not in CLASS_KEYS and k != 'reason':
                    yield [str(k)], s, ((v if isinstance(v, str) and v.lower() not in GENERIC else ''), ''), hint
            elif isinstance(v, dict):
                s = None
                sw = None
                for sk in STATUS_KEYS:
                    if sk in v:
                        s = norm_status(v[sk])
                        if s:
                            sw = v[sk]
                            break
                if s and not any(ik in v for ik in ('node_id', 'nodeid', 'name', 'id')):
                    yield [str(k)], s, (get_class(v, sw), get_msg(v)), hint
            if isinstance(v, (dict, list)):
                yield from walk_records(v, path + (str(k),))
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_records(v, path)


def digits(s):
    return re.findall(r'\d+', s)


def config_aliases(cfg, nodes):
    """Map alternate ids (test_id > pr_number > pr > name) declared in config.json to node ids.
    Higher-priority keys win; an alias is dropped only if ambiguous within its own key."""
    per_key = {k: {} for k in ('test_id', 'pr_number', 'pr', 'name')}
    def walk(o):
        if isinstance(o, dict):
            nid = o.get('node_id') or o.get('id')
            if isinstance(nid, str) and nid in nodes:
                for k in per_key:
                    v = o.get(k)
                    if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v) != nid:
                        per_key[k].setdefault(str(v), set()).add(nid)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(cfg)
    al = {}
    for k in per_key:
        for a, ns in per_key[k].items():
            if len(ns) == 1 and a not in al:
                al[a] = next(iter(ns))
    return al


class Matcher:
    def __init__(self, f2p, p2p, aliases=None):
        self.aliases = aliases or {}
        self.nodes = [('f2p', n) for n in f2p] + [('p2p', n) for n in p2p]
        self.exact = {}
        for c, n in self.nodes:
            self.exact.setdefault(n, []).append(c)
        self.lower = {}
        for c, n in self.nodes:
            self.lower.setdefault(self.canon(n), set()).add(n)
        dig = {}
        for c, n in self.nodes:
            ds = digits(n)
            if ds:
                key = str(int(max(ds, key=len)))
                dig.setdefault(key, set()).add(n)
        self.dig = {k: next(iter(v)) for k, v in dig.items() if len(v) == 1}

    @staticmethod
    def canon(s):
        s = s.strip().lower()
        s = re.sub(r'^\[(f2p|p2p)\]\s*', '', s)
        s = re.sub(r'^(f2p|p2p)[\s:_\-/]+', '', s)
        return re.sub(r'[^a-z0-9]+', '_', s).strip('_')

    def match(self, cands, allow_digits):
        for c in cands:
            if c in self.exact:
                return c
        for c in cands:
            if c in self.aliases:
                return self.aliases[c]
        for c in cands:
            hit = self.lower.get(self.canon(c))
            if hit and len(hit) == 1:
                return next(iter(hit))
        # strip common prefixes
        for c in cands:
            cc = self.canon(c)
            for pre in ('pr_', 'node_', 'behavior_', 'test_', 'f2p_', 'p2p_'):
                for n in self.exact:
                    if self.canon(n) == pre + cc or cc == pre + self.canon(n):
                        return n
        if allow_digits:
            for c in cands:
                ds = digits(c)
                if len(ds) >= 1:
                    key = str(int(max(ds, key=len)))
                    if len(key) >= 2 and key in self.dig:
                        return self.dig[key]
        return None


def extract_json(path, matcher, allow_digits):
    try:
        if path.endswith('.jsonl'):
            objs = [json.loads(l) for l in open(path, errors='ignore') if l.strip()]
        else:
            objs = [json.load(open(path, errors='ignore'))]
    except Exception:
        return None
    res = {}
    for o in objs:
        for ids, st, fc, hint in walk_records(o):
            n = matcher.match(ids, allow_digits)
            if n is None:
                continue
            # first record wins for status (top-level records appear before nested duplicates);
            # later records with the same status may only enrich an empty failure label / message
            if n not in res:
                res[n] = (st, fc)
            elif res[n][0] == st and st == 'failed':
                (r0, m0), (r1, m1) = res[n][1], fc
                res[n] = (st, (r0 or r1, m0 or m1))
    return res


TEXT_PATTERNS = [
    # pytest -rA style: PASSED tests/test_outputs.py::test_unit[597]
    re.compile(r'^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+(\S+)', re.M),
    # pytest verbose: tests/x.py::test[1] PASSED
    re.compile(r'^(\S+::\S+)\s+(PASSED|FAILED|ERROR|SKIPPED)', re.M),
    # NODE <id> PASS/FAIL, node <id>: passed
    re.compile(r'(?i)\b(?:node|pr|behavior|test)[\s:#-]*([\w./:\[\]-]+)\s*[:=\-]?\s*(passed|failed|pass|fail|ok|error)\b'),
    re.compile(r'(?i)^\s*(PASS|FAIL|OK|ERROR)\b[\s:\-]+([\w./:\[\]-]+)', re.M),
    re.compile(r'(?i)^\s*\[(PASS|FAIL|PASSED|FAILED|OK|ERROR)\]\s+([\w./:\[\]-]+)', re.M),
    re.compile(r'(?i)^\s*([\w./:\[\]-]+)\s*[:=]\s*(PASS|FAIL|PASSED|FAILED|OK|ERROR)\b', re.M),
]


def extract_text(path, matcher, allow_digits):
    try:
        s = open(path, errors='ignore').read()
    except Exception:
        return None
    best = None
    for pat in TEXT_PATTERNS:
        res = {}
        for m in pat.finditer(s):
            a, b = m.group(1), m.group(2)
            if norm_status(a.lower()) or a.upper() in ('XFAIL', 'XPASS', 'SKIPPED'):
                stw, idw = a, b
            else:
                idw, stw = a, b
            st = 'passed' if stw.lower() in ('pass', 'passed', 'ok', 'xpass') else 'failed'
            n = matcher.match([idw], allow_digits)
            if n is None:
                continue
            res[n] = (st, ('', ''))  # last occurrence wins (summaries come last)
        if best is None or len(res) > len(best):
            best = res
    return best


def normalize_class(raw, msg):
    """Coarse failure taxonomy. Explicit grader labels take precedence; message text is a fallback."""
    r = (raw or '').lower()
    def by_label(x):
        if not x:
            return None
        if any(w in x for w in ('infra', 'environment', 'harness', 'runner_error', 'setup', 'blocked', 'dependency')):
            return 'infrastructure_or_blocked'
        if 'skip' in x:
            return 'infrastructure_or_blocked'
        if 'timeout' in x or 'timed_out' in x:
            return 'timeout'
        if 'compil' in x or 'compile' in x or 'build' in x:
            return 'solver_compile_error'
        if 'load' in x or 'runtime' in x or 'import' in x:
            return 'solver_runtime_or_load_error'
        if any(w in x for w in ('behav', 'assert', 'function', 'product', 'contract', 'f2p_failed', 'p2p_failed',
                                'test_error', 'systemexit', 'pytest_failed', 'suite_failed', 'tap_failed', 'fail')):
            return 'functional_failed'
        return None
    c = by_label(r)
    if c:
        return c
    m = msg or ''
    if re.search(r'error CS\d+|error\[E\d+\]|cannot find symbol|compilation (failed|error)|COMPILATION ERROR|'
                 r'error TS\d+|does not compile|undefined reference|go build|build failed', m, re.I):
        return 'solver_compile_error'
    if re.search(r'timed out|timeout', m, re.I):
        return 'timeout'
    if re.search(r'ModuleNotFoundError|ImportError|LoadError|Cannot find module|NoClassDefFoundError|'
                 r'ClassNotFoundException|NameError|is not a function|TypeError|NoMethodError|panicked', m):
        return 'solver_runtime_or_load_error'
    if re.search(r'assert|expected|Failure:|mismatch|!==|should|not equal', m, re.I):
        return 'functional_failed'
    return 'unspecified'


def evidence_dir(row):
    o = json.load(open(os.path.join(INPUTS, row, 'outcome.json')))
    src = o['score_snapshot'].get('source', '')
    acc = os.path.join(INPUTS, row, 'accepted-recovery-private', 'run', 'verifier', 'logs')
    raw = os.path.join(INPUTS, row, 'raw-private', 'run', 'verifier', 'logs')
    if 'accepted recovery' in src and os.path.isdir(acc):
        return acc, 'accepted-recovery', src
    if 'accepted recovery' in src:
        # recovery accepted but recovery dir has no verifier logs: recovery re-used original evidence
        orig = glob.glob(os.path.join(INPUTS, row, 'accepted-recovery-private', 'job', 'original-evidence',
                                      'runs', '*', 'verifier', 'logs'))
        if orig:
            return orig[0], 'accepted-recovery(original-evidence)', src
    return raw, 'raw', src


def supplemental(row, base, f2p, p2p):
    """Per-row extra evidence for nodes the main per-node file does not carry.
    Returns {node: (status, class, path)}. Each entry is explicit and documented."""
    sup = {}
    v = os.path.join(base, 'verifier')
    if row == '018':
        # P2P nodes are graded from verifier/<test_name>-phases.json (pytest phases, exit code)
        for n in p2p:
            f = os.path.join(v, n.split('::')[-1] + '-phases.json')
            if os.path.exists(f):
                d = json.load(open(f))
                ok = d.get('exit') == 0 and all(ph.get('outcome') == 'passed' for ph in d.get('phases', [])) \
                    and d.get('phases')
                sup[n] = ('passed' if ok else 'failed', ('' if ok else 'pytest_failed', ''), f)
    if row == '043' and len(p2p) == 1:
        # single aggregate P2P node: reward.json p2p_exit + verifier/p2p.log minitest summary
        d = json.load(open(os.path.join(v, 'reward.json')))
        ok = d.get('p2p_exit') == 0
        sup[p2p[0]] = ('passed' if ok else 'failed', ('' if ok else 'suite_failed', ''), os.path.join(v, 'p2p.log'))
    if row == '078' and len(p2p) == 1:
        # single P2P regression node: verifier/format-regression.log (node --test TAP summary)
        f = os.path.join(v, 'format-regression.log')
        t = open(f, errors='ignore').read()
        m = re.findall(r'^# fail (\d+)', t, re.M)
        p = re.findall(r'^# pass (\d+)', t, re.M)
        ok = bool(m) and m[-1] == '0' and p and int(p[-1]) > 0
        sup[p2p[0]] = ('passed' if ok else 'failed', ('' if ok else 'tap_failed', ''), f)
    return sup


def candidate_files(base):
    fs = [f for f in glob.glob(os.path.join(base, '**', '*'), recursive=True)
          if os.path.isfile(f) and '/artifacts/' not in f and os.path.getsize(f) < 80e6]
    def prio(f):
        b = os.path.basename(f)
        if b == 'ctrf.json':
            return (0, f)
        if 'private-runtime' in f:
            return (5, f)
        if b.endswith('.json') or b.endswith('.jsonl'):
            if b.startswith(('source-reward', 'adapter', 'reward', 'rewards', 'source-rewards')):
                return (3, f)
            return (1, f)
        if b.endswith(('.log', '.txt', '.out')):
            return (2 if b in ('test-stdout.log',) else 4, f)
        return (6, f)
    return sorted(fs, key=prio)


def counts(res, f2p, p2p):
    fp = sum(1 for n in f2p if res.get(n, ('failed',))[0] == 'passed')
    pp = sum(1 for n in p2p if res.get(n, ('failed',))[0] == 'passed')
    return fp, pp


def main():
    tasks = load_tasks()
    runs = list(csv.DictReader(open(RUNS)))
    node_rows, rec_rows = [], []
    for r in runs:
        row = r['row']
        t = tasks[row]
        f2p, p2p = t['f2p'], t['p2p']
        exp = (int(r['f2p_passed']), int(r['p2p_passed']))
        assert len(f2p) == int(r['f2p_total']) and len(p2p) == int(r['p2p_total']), row
        base, how, src = evidence_dir(row)
        m = Matcher(f2p, p2p, t['aliases'])
        chosen = None
        tried = []
        allf = candidate_files(base) if os.path.isdir(base) else []
        sup = supplemental(row, base, f2p, p2p) if os.path.isdir(base) else {}
        for allow_digits in (False, True):
            for f in allf:
                ext = extract_json if f.endswith(('.json', '.jsonl')) else extract_text
                res = ext(f, m, allow_digits)
                if not res:
                    continue
                res = dict(res)
                for n, (st_, fc_, pth) in sup.items():
                    if n not in res:
                        res[n] = (st_, fc_, pth)
                cov = sum(1 for n in f2p + p2p if n in res)
                got = counts(res, f2p, p2p)
                tried.append((os.path.relpath(f, base), cov, got))
                # require full coverage, or coverage of all passes with missing nodes treated as failed
                if got == exp and cov >= 0.5 * len(f2p + p2p):
                    if chosen is None or cov > chosen[2]:
                        chosen = (f, res, cov, allow_digits)
                    if cov == len(f2p + p2p):
                        break
            if chosen and chosen[2] == len(f2p + p2p):
                break
        if chosen:
            f, res, cov, ad = chosen
            fp, pp = counts(res, f2p, p2p)
            missing = [n for n in f2p + p2p if n not in res]
            for cls, lst in (('f2p', f2p), ('p2p', p2p)):
                for n in lst:
                    ev = f
                    if n in res:
                        st, (raw, msg) = res[n][0], res[n][1]
                        if len(res[n]) > 2:
                            ev = res[n][2]
                        fc = normalize_class(raw, msg) if st == 'failed' else ''
                        raw = raw if st == 'failed' else ''
                    else:
                        st, fc, raw = 'failed', 'not_reported', ''
                    node_rows.append([row, r['run_id'], r['task_version'], cls, n, st, fc, ev, raw])
            notes = f'evidence={how}; file={os.path.relpath(f, INPUTS)}; coverage={cov}/{len(f2p+p2p)}'
            if missing:
                notes += f'; {len(missing)} nodes absent from evidence counted as failed(not_reported)'
            if ad:
                notes += '; numeric-id matching used'
            used_sup = [n for n in sup if n in res and len(res[n]) > 2]
            if used_sup:
                notes += '; supplemental evidence for ' + ','.join(used_sup)
            rec_rows.append([row, r['f2p_passed'], r['f2p_total'], fp, r['p2p_passed'], r['p2p_total'], pp,
                             True, 'per-node:' + os.path.basename(f), notes])
        else:
            for cls, lst in (('f2p', f2p), ('p2p', p2p)):
                for n in lst:
                    node_rows.append([row, r['run_id'], r['task_version'], cls, n, 'unresolved', '', base, ''])
            best = max(tried, key=lambda x: x[1]) if tried else None
            notes = f'evidence={how}; source={src}; no per-node evidence reproduces expected counts'
            if not os.listdir(base) if os.path.isdir(base) else True:
                notes += '; verifier logs dir missing/empty'
            g = os.path.join(INPUTS, row, 'raw-private', 'job', 'GRADE.json')
            if os.path.exists(g):
                gd = json.load(open(g))
                if gd.get('reward') is None:
                    notes += (f"; GRADE.json reward=null exit={gd.get('verifier_exit_code')} errors={gd.get('errors')}"
                              '; selected score exists only in outcome.json score_snapshot, no per-node source retained')
            if best:
                notes += f'; best candidate {best[0]} covered {best[1]} nodes giving f2p/p2p={best[2]}'
            rec_rows.append([row, r['f2p_passed'], r['f2p_total'], '', r['p2p_passed'], r['p2p_total'], '',
                             False, 'unresolved', notes])
    with open(os.path.join(OUT, 'NODE_OUTCOMES.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['row', 'run_id', 'task_version', 'node_class', 'node_id', 'status', 'failure_class', 'evidence_path', 'failure_label_raw'])
        w.writerows(node_rows)
    with open(os.path.join(OUT, 'RECONCILE.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['row', 'expected_f2p_passed', 'f2p_total', 'reconstructed_f2p_passed', 'expected_p2p_passed',
                    'p2p_total', 'reconstructed_p2p_passed', 'match', 'method', 'notes'])
        w.writerows(rec_rows)
    ok = sum(1 for x in rec_rows if x[7])
    print(f'reconciled {ok}/{len(rec_rows)}')
    for x in rec_rows:
        if not x[7]:
            print(x[0], x[-1])


if __name__ == '__main__':
    main()
