#!/usr/bin/env python3
"""Validate a cowork-failure-diagnosis report: schema, identity, coverage of failed requirements,
exact behaviour citations, and context references.

    python3 scripts/validate_diagnosis.py REPORT.json BEHAVIOR_DIR CONTEXT_DIR
"""
import argparse
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parents[1]


def strings(value):
    if isinstance(value, str):
        yield value
        if value.lstrip().startswith(('{', '[')):
            try:
                decoded = json.loads(value)
            except (ValueError, TypeError):
                return
            if not isinstance(decoded, str):
                yield from strings(decoded)
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def validate(report, behavior, context, schema_path=None):
    import jsonschema
    behavior, context = Path(behavior).resolve(), Path(context).resolve()
    schema = json.loads(Path(schema_path or HERE / 'references/output.schema.json').read_text())
    V = getattr(jsonschema, 'Draft202012Validator', None) or jsonschema.Draft7Validator
    errors = [f'schema: {"/".join(map(str, e.path))}: {e.message}' for e in V(schema).iter_errors(report)]
    if errors:
        return errors
    ctx = json.loads((context / 'CONTEXT.json').read_text())
    ident = ctx['identity']
    for k in ('task_id', 'task_version', 'run_id'):
        if report['task'][k] != ident[k]:
            errors.append('task identity mismatch: ' + k)
    if int(report['task']['row']) != int(ident['row']):
        errors.append('task identity mismatch: row')
    for k in ('f2p_passed', 'f2p_total', 'p2p_passed', 'p2p_total'):
        if report['outcome'][k] != ctx['outcome'][k]:
            errors.append('outcome mismatch: ' + k)
    failed = {r['req_id'] for r in ctx['requirements'] if r['nodes_total'] and r['nodes_passed'] < r['nodes_total']}
    covered = {r['req_id'] for r in report['requirements']}
    missing = sorted(failed - covered)
    if missing:
        errors.append('failed requirements not diagnosed: ' + ','.join(missing))
    known_reqs = {r['req_id'] for r in ctx['requirements']}
    for r in report['requirements']:
        if r['req_id'] not in known_reqs:
            errors.append('unknown requirement: ' + r['req_id'])
        if not r['what_happened']:
            errors.append('empty chain: ' + r['req_id'])
        if r['stage'] not in ('not_determinable', 'infrastructure') and not any(s['evidence_ids'] for s in r['what_happened']):
            errors.append('chain without trajectory evidence: ' + r['req_id'])
    # evidence records
    ids = [e['id'] for e in report['evidence']]
    if len(ids) != len(set(ids)):
        errors.append('duplicate evidence IDs')
    cache = {}
    for item in report['evidence']:
        name = item['path']
        path = (behavior / name).resolve()
        if Path(name).is_absolute() or not path.is_relative_to(behavior) or not path.is_file():
            errors.append('invalid evidence path: ' + name)
            continue
        if path not in cache:
            cache[path] = path.read_text().splitlines()
        lines = cache[path]
        a, b = item['line_start'], item['line_end']
        if not 1 <= a <= b <= len(lines):
            errors.append('invalid line range: ' + item['id'])
            continue
        section = lines[a - 1:b]
        cands = ['\n'.join(section)]
        for line in section:
            try:
                cands.extend(strings(json.loads(line)))
            except ValueError:
                pass
        norm = lambda x: re.sub(r'\s+', ' ', x).strip()
        if not item['quote'].strip() or not any(norm(item['quote']) in norm(t) for t in cands):
            errors.append('quote not found in cited lines: ' + item['id'])
        if item['event_id'] and not any(item['event_id'] in t for t in cands):
            errors.append('event ID not found in cited lines: ' + item['id'])
    known = set(ids)
    nodes = {n['node_id'] for r in ctx['requirements'] for n in r['nodes']} | {n['node_id'] for n in ctx.get('p2p_failed', [])}
    ref_ok = re.compile(r'^(req|spec):(.+)$|^node:(.+)$|^p2p:(.+)$|^note$|^outcome$|^deferral:(.+)$')

    def walk(v):
        if isinstance(v, dict):
            for k, c in v.items():
                if k == 'evidence_ids':
                    for ref in c:
                        if ref not in known:
                            errors.append('unknown evidence reference: ' + ref)
                elif k == 'context_refs':
                    for ref in c:
                        m = ref_ok.match(ref)
                        if not m:
                            errors.append('malformed context ref: ' + ref)
                        elif ref.startswith(('req:', 'spec:')) and ref.split(':', 1)[1] not in known_reqs:
                            errors.append('context ref to unknown requirement: ' + ref)
                        elif ref.startswith(('node:', 'p2p:')) and ref.split(':', 1)[1] not in nodes:
                            errors.append('context ref to unknown node: ' + ref)
                else:
                    walk(c)
        elif isinstance(v, list):
            for c in v:
                walk(c)
    walk({k: v for k, v in report.items() if k != 'evidence'})
    if re.search(r'\b(?:E|Q)\d{1,3}\b|node:|req:|spec:', report['case_paragraph']):
        errors.append('case_paragraph must not contain evidence/context IDs; put them in case_evidence_ids')
    if not report['case_evidence_ids']:
        errors.append('case_evidence_ids is empty')
    words = len(re.findall(r'[一-鿿]|[A-Za-z0-9_]+', report['case_paragraph']))
    if words < 80:
        errors.append(f'case_paragraph too short ({words} words/characters)')
    return errors


def main():
    p = argparse.ArgumentParser()
    p.add_argument('report')
    p.add_argument('behavior')
    p.add_argument('context')
    p.add_argument('--schema')
    a = p.parse_args()
    try:
        errors = validate(json.loads(Path(a.report).read_text()), a.behavior, a.context, a.schema)
    except Exception as exc:
        print(json.dumps({'valid': False, 'errors': [f'{type(exc).__name__}: {exc}']}, ensure_ascii=False))
        return 1
    print(json.dumps({'valid': not errors, 'errors': errors}, ensure_ascii=False))
    return bool(errors)


if __name__ == '__main__':
    sys.exit(main())
