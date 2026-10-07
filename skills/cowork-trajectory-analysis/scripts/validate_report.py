#!/usr/bin/env python3
"""Validate annotation structure, task binding and exact local evidence citations."""
import argparse
import json
from pathlib import Path
import re
import sys

STRATEGY = {
    'search_strategy', 'decomposition_prioritization', 'hypothesis_testing',
    'information_value', 'abstraction_transfer', 'causal_debugging',
    'feedback_adaptation', 'information_integration', 'verification_design',
    'calibration_stopping',
}
COLLABORATION = {
    'scope_reconstruction', 'provenance_version_reconciliation',
    'owner_question_followthrough', 'notification_handling',
    'evidence_to_implementation', 'delivery_accountability',
}


def strings(value):
    if isinstance(value, str):
        yield value
        # Tool output sometimes contains an embedded JSON serialization.
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


def validate(report, input_dir, schema_path=None):
    import jsonschema
    input_dir = Path(input_dir).resolve()
    schema_path = Path(schema_path or Path(__file__).resolve().parents[1] / 'references/output.schema.json')
    Validator = getattr(jsonschema, 'Draft202012Validator', None) or jsonschema.Draft7Validator
    errors = [str(e.message) for e in Validator(json.loads(schema_path.read_text())).iter_errors(report)]
    if errors:
        return errors
    source = json.loads((input_dir / 'INPUTS.json').read_text())
    identity = source.get('identity', source)
    for name, value in report['task'].items():
        expected = identity.get(name)
        if name == 'row':
            try:
                matched = int(value) == int(expected)
            except (ValueError, TypeError):
                matched = False
        else:
            matched = value == expected
        if not matched:
            errors.append('task identity mismatch: ' + name)
    for field, expected in [('strategy_dimensions', STRATEGY), ('collaboration_dimensions', COLLABORATION)]:
        dims = report[field]
        ids = [d['id'] for d in dims]
        if len(ids) != len(set(ids)) or set(ids) != expected:
            errors.append('dimension set mismatch: ' + field)
        for dim in dims:
            if dim['observation_status'] != 'observed' and dim['score'] is not None:
                errors.append('non-observed dimension has a score: ' + dim['id'])
            if dim['score'] is not None and not dim['evidence_ids']:
                errors.append('scored dimension lacks evidence: ' + dim['id'])
    evidence = report['evidence']
    evidence_ids = [e['id'] for e in evidence]
    if not evidence or len(set(evidence_ids)) != len(evidence_ids):
        errors.append('empty evidence or duplicate IDs')
    ids = set(evidence_ids)
    line_cache = {}
    for item in evidence:
        name = item['path']
        path = (input_dir / name).resolve()
        if Path(name).is_absolute() or not path.is_relative_to(input_dir) or not path.is_file():
            errors.append('invalid evidence path: ' + name)
            continue
        if path not in line_cache:
            line_cache[path] = path.read_text().splitlines()
        lines = line_cache[path]
        start, end = item['line_start'], item['line_end']
        if not 1 <= start <= end <= len(lines):
            errors.append('invalid line range: ' + item['id'])
            continue
        section = lines[start - 1:end]
        candidates = ['\n'.join(section)]
        for line in section:
            try:
                candidates.extend(strings(json.loads(line)))
            except ValueError:
                pass
        quote = item['quote']
        norm = lambda x: re.sub(r'\s+', ' ', x).strip()
        if not quote.strip() or not any(norm(quote) in norm(text) for text in candidates):
            errors.append('quote not found in cited lines: ' + item['id'])
        if item['event_id'] and not any(item['event_id'] in text for text in candidates):
            errors.append('event ID not found in cited lines: ' + item['id'])
    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ('evidence_ids', 'counterevidence_ids'):
                    for ref in child:
                        if ref not in ids:
                            errors.append('unknown evidence reference: ' + ref)
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(report)
    actions = input_dir / 'actions.jsonl'
    if actions.exists():
        with actions.open() as stream:
            total = sum(bool(line.strip()) for line in stream)
        coverage = report['coverage']
        if coverage['total_actions'] != total:
            errors.append('coverage total_actions mismatch')
        if not 0 <= coverage['examined_actions'] <= total:
            errors.append('invalid examined action count')
        if coverage['action_index_fully_examined'] and coverage['examined_actions'] != total:
            errors.append('full coverage claimed without all actions')
    for name in report['coverage']['files_examined']:
        path = (input_dir / name).resolve()
        if Path(name).is_absolute() or not path.is_relative_to(input_dir) or not path.is_file():
            errors.append('invalid examined file: ' + name)
    return errors


def main():
    p = argparse.ArgumentParser()
    p.add_argument('report')
    p.add_argument('input_dir')
    p.add_argument('--schema')
    args = p.parse_args()
    try:
        errors = validate(json.loads(Path(args.report).read_text()), args.input_dir, args.schema)
    except Exception as exc:
        print(json.dumps({'valid': False, 'errors': [str(exc)]}, ensure_ascii=False))
        return 1
    print(json.dumps({'valid': not errors, 'errors': errors}, ensure_ascii=False))
    return bool(errors)


if __name__ == '__main__':
    sys.exit(main())
