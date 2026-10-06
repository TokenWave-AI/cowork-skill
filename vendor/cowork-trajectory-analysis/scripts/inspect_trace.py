#!/usr/bin/env python3
"""Read bounded action summaries or exact normalized events without silent truncation."""
import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('input_dir')
    p.add_argument('--view', choices=['actions', 'evidence', 'sidecar'], default='actions')
    p.add_argument('--start', type=int, default=1)
    p.add_argument('--end', type=int, default=30)
    p.add_argument('--event-id')
    p.add_argument('--offset', type=int, default=0)
    p.add_argument('--limit', type=int, default=20000)
    p.add_argument('--preview', type=int, default=400)
    args = p.parse_args()
    path = Path(args.input_dir) / (args.view + '.jsonl')
    with path.open() as stream:
        for n, line in enumerate(stream, 1):
            if not args.event_id and not args.start <= n <= args.end:
                continue
            item = json.loads(line)
            if args.event_id and item.get('event_id') != args.event_id:
                continue
            if args.view == 'actions':
                payload = json.dumps(item.get('input'), ensure_ascii=False)
                out = {key: item.get(key) for key in ['action_id', 'order', 'canonical_tool', 'call_time', 'pairing_status', 'call_evidence']}
                out['input_preview'] = payload[:args.preview]
                out['input_chars'] = len(payload)
                out['input_truncated'] = len(payload) > args.preview
                out['results'] = item.get('results')
                print(json.dumps({'line': n, **out}, ensure_ascii=False))
            else:
                text = json.dumps(item, ensure_ascii=False, indent=2)
                selected = text[args.offset:args.offset + args.limit]
                print(json.dumps({'path': path.name, 'line': n, 'event_id': item.get('event_id'), 'characters': len(text), 'offset': args.offset, 'returned': len(selected), 'more': args.offset + len(selected) < len(text)}, ensure_ascii=False))
                print(selected)


if __name__ == '__main__':
    main()
