#!/usr/bin/env python3
"""Read-only SSH (or local) acquisition and reproducible normalization of selected CoWork runs.

Adapted for cowork-model-report-skill from the Opus-5.5 campaign (opus55-astra-trajectory-20261003).
Normalisation logic is unchanged.  Parametrised: --campaign (output root), --status-dir
(CURRENT_SCORES.csv + TRAJECTORY_INDEX.csv), --hosts-bundle (BUNDLE.json with hosts[].ssh, or
omit / use host id 'local' for trajectories on this machine), --bundle (public release),
--recoveries (optional JSON list of accepted recoveries), --excluded-rows.

No solver/model/container invocation. Original bytes are copied to raw-private,
SHA-256 verified and made read-only. Behavior files never contain grade tables.
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import csv
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import threading

ROOT = None      # campaign root, set in main()
STATUS = None    # status dir with CURRENT_SCORES.csv / TRAJECTORY_INDEX.csv
BUNDLE = None    # hosts bundle JSON (optional)
RELEASE = None   # public release bundle
RECOVERIES = None
EXCLUDED = []
LOCK = threading.Lock()
SCHEMA = 'opus55-behavior-input-v1'

REMOTE_FETCH = r'''
import hashlib,io,json,os,pathlib,sys,tarfile,time
spec=SPEC
job=pathlib.Path(spec['job_root']);run=pathlib.Path(spec['run_root'])
selected={str(pathlib.Path(p).parent) for p in spec['trajectories']}
suffixes={'.json','.jsonl','.log','.patch','.diff','.md','.txt','.stdout','.stderr','.yaml','.yml','.csv','.sh'}
files={};omitted=[]
for label,root in [('job',job),('run',run)]:
 if not root.is_dir():continue
 for parent,dirs,names in os.walk(root,followlinks=False):
  parent=pathlib.Path(parent)
  dirs[:]=[x for x in dirs if x not in ['.git','node_modules','workspace','code','repo','.venv','venv']+spec.get('exclude_dirs',[]) and not (parent/x).is_symlink()]
  if label=='job' and parent==job:dirs[:]=[x for x in dirs if x!='runs']
  if label=='job' and parent==job/'attempts':dirs[:]=[x for x in dirs if str(parent/x) in selected]
  for name in names:
   p=parent/name
   if p.is_symlink() or not p.is_file():continue
   arc=label+'/'+str(p.relative_to(root))
   if p.suffix not in suffixes and name not in ['stdout','stderr']:
    omitted.append({'remote_path':str(p),'reason':'non-evidence extension/lock/binary','bytes':p.stat().st_size});continue
   files[arc]=p
manifest={'schema':'raw-acquisition-v1','fetched_at':time.time(),'host':spec['host'],'row':spec['row'],'run_id':spec['run_id'],'job_root':str(job),'run_root':str(run),'files':[],'omitted':omitted}
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz',compresslevel=1) as tar:
 for arc,p in sorted(files.items()):
  before=p.stat(); data=p.read_bytes();after=p.stat()
  if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise RuntimeError('source changed while reading '+str(p))
  item={'path':arc,'remote_path':str(p),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'mtime_ns':after.st_mtime_ns}
  manifest['files'].append(item)
  ti=tarfile.TarInfo(arc);ti.size=len(data);ti.mode=0o444;ti.mtime=after.st_mtime
  tar.addfile(ti,io.BytesIO(data))
 data=json.dumps(manifest,ensure_ascii=False,indent=2).encode()
 ti=tarfile.TarInfo('ACQUISITION.json');ti.size=len(data);ti.mode=0o444
 tar.addfile(ti,io.BytesIO(data))
'''


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{os.getpid()}.{threading.get_ident()}.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def sha_file(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def compact(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))


def read_json(path, default=None):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return default


def source_snapshot():
    dest = ROOT / 'manifests/source-snapshots'
    dest.mkdir(parents=True, exist_ok=True)
    files = [STATUS / n for n in ['CURRENT_SCORES.csv', 'TRAJECTORY_INDEX.csv', 'TRAJECTORY_RETENTION_SUMMARY.json', 'PROVIDER_ACCESS_HOLD_016_026.json', 'CURRENT_SCORE_SUMMARY.json', 'LIVE_FOLLOWUP_LATEST.json']]
    files += [RELEASE / 'MANIFEST.json', RELEASE / 'runtime/RUNTIME_VARIANTS.json']
    records = []
    for src in files:
        if not src.exists():
            continue
        name = ('release-' if src.is_relative_to(RELEASE) else '') + src.name
        dst = dest / name
        digest = sha_file(src)
        if dst.exists():
            if sha_file(dst) != digest:
                raise RuntimeError(f'Pinned source changed: {src}')
        else:
            shutil.copyfile(src, dst)
            dst.chmod(0o444)
        records.append({'source_path': str(src), 'snapshot_path': str(dst), 'sha256': digest, 'bytes': dst.stat().st_size})
    dump(ROOT / 'manifests/source-snapshot-manifest.json', records)
    return dest


def selection(snapshot):
    scores = {int(x['row']): x for x in csv.DictReader((snapshot / 'CURRENT_SCORES.csv').open())}
    groups = {}
    for x in csv.DictReader((snapshot / 'TRAJECTORY_INDEX.csv').open()):
        if x['selected_for_current_score'] != 'True':
            continue
        row = int(x['row'])
        p = Path(x['trajectory_path'])
        job = p.parents[2]
        run = job.parents[1] / 'runs' / x['run_id']
        g = groups.setdefault(row, {'row': row, 'host': x['host'], 'run_id': x['run_id'], 'job_root': str(job), 'run_root': str(run), 'trajectories': [], 'indexed_bytes': {}, 'score': scores[row]})
        assert (g['host'], g['run_id'], g['job_root']) == (x['host'], x['run_id'], str(job))
        g['trajectories'].append(str(p))
        g['indexed_bytes'][str(p)] = int(x['bytes'])
    for g in groups.values():
        g['trajectories'].sort()
    return groups


def acquire(g, hosts, raw_subdir='raw-private'):
    rowdir = ROOT / 'inputs' / f"{g['row']:03d}"
    raw = rowdir / raw_subdir
    ready = raw / 'ACQUISITION.json'
    if ready.exists():
        existing = read_json(ready)
        assert existing['run_id'] == g['run_id']
        return existing
    raw.mkdir(parents=True, exist_ok=True)
    raw.chmod(0o700)
    h = (hosts.get(g['host']) or {}).get('ssh')
    cmd = ['python3', '-'] if not h or g['host'] == 'local' else ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=20', '-o', 'ServerAliveCountMax=3', '-o', 'UserKnownHostsFile=' + h['known_hosts'], '-i', h['identity_file'], '-p', str(h['port']), h['user'] + '@' + h['host'], 'python3 -']
    (ROOT / 'manifests').mkdir(parents=True, exist_ok=True)
    public_spec = {k: v for k, v in g.items() if k not in ['score', 'indexed_bytes']}
    code = REMOTE_FETCH.replace('SPEC', repr(public_spec), 1)
    errpath = ROOT / 'manifests' / f"fetch-{g['row']:03d}.stderr.log"
    with errpath.open('wb') as err:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err)
        proc.stdin.write(code.encode()); proc.stdin.close()
        try:
            with tarfile.open(fileobj=proc.stdout, mode='r|gz') as tar:
                for member in tar:
                    path = Path(member.name)
                    if not member.isfile() or path.is_absolute() or '..' in path.parts:
                        raise RuntimeError('Unsafe acquisition archive path')
                    dest = raw / path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    tmp = dest.with_name(dest.name + '.partial')
                    with tmp.open('wb') as out:
                        shutil.copyfileobj(tar.extractfile(member), out)
                    if dest.exists() and sha_file(dest) != sha_file(tmp):
                        raise RuntimeError(f'Immutable raw differs: {dest}')
                    tmp.replace(dest)
                    dest.chmod(0o444)
        except Exception:
            proc.kill(); proc.wait()
            raise
        if proc.wait() != 0:
            raise RuntimeError(f"SSH fetch failed for row {g['row']}; see {errpath}")
    acquisition = read_json(ready)
    if not acquisition:
        raise RuntimeError('Acquisition manifest missing')
    failures = []
    for f in acquisition['files']:
        if sha_file(raw / f['path']) != f['sha256']:
            failures.append(f['path'])
    if failures:
        raise RuntimeError(f'Hash mismatch: {failures}')
    return acquisition


def ref(event_id, filename, line, raw_info, raw_line, pointer=None):
    out = {'event_id': event_id, 'path': filename, 'line_start': line, 'line_end': line,
           'raw_path': raw_info['path'], 'remote_path': raw_info['remote_path'],
           'raw_line': raw_line, 'raw_sha256': raw_info['sha256']}
    if pointer:
        out['json_pointer'] = pointer
    return out


def message_ids(value):
    """Find actual dynamic message objects, including JSON carried in MCP text."""
    if isinstance(value, str):
        if value.lstrip().startswith(('{', '[')):
            try:
                yield from message_ids(json.loads(value))
            except ValueError:
                pass
    elif isinstance(value, list):
        for v in value:
            yield from message_ids(v)
    elif isinstance(value, dict):
        mid = value.get('id') or value.get('message_id')
        if isinstance(mid, str) and mid.startswith('runtime-') and any(k in value for k in ['text', 'body', 'content']):
            yield value
        for v in value.values():
            yield from message_ids(v)


def strip_private_keys(obj):
    """Only strip computed outcome and credential fields from derived metadata."""
    if isinstance(obj, dict):
        return {k: strip_private_keys(v) for k, v in obj.items()
                if not (re.search(r'(^|_)(f2p|p2p|reward|grade|grading|score|review_flagged)(_|$)', k.lower())
                        or re.search(r'(api_key|password|secret|authorization|access_token)', k.lower()))}
    if isinstance(obj, list):
        return [strip_private_keys(v) for v in obj]
    return obj


def normalize(g, acquisition):
    row = g['row']; rowname = f'{row:03d}'
    rowdir = ROOT / 'inputs' / rowname
    raw = rowdir / 'raw-private'; out = rowdir / 'behavior'
    previous = read_json(ROOT/'manifests'/f'{rowname}.json')
    if previous and previous.get('status') == 'ready':
        if previous['run_id'] != g['run_id']:
            raise RuntimeError('Frozen behavior run identity changed')
        for f in previous['input_files']:
            if sha_file(out/f['path']) != f['sha256']:
                raise RuntimeError(f"Frozen behavior hash changed: {rowname}/{f['path']}")
        with LOCK:
            print(json.dumps({'row':row,'status':'reused_frozen_behavior'}),flush=True)
        return previous
    out.mkdir(exist_ok=True)
    fs = {f['path']: f for f in acquisition['files']}
    evidence_path = out / 'evidence.jsonl'
    actions = []; by_id = {}; orphan_results = []; seen_uuid = {}; seen_payload = {}
    exposures = []; seen_messages = {}; heartbeat = collections.Counter(); counts = collections.Counter()
    sessions = set(); inits = []; result_events = []; faults = []; parse_errors = []; attempt_stats = []
    en = 0; init_segment = 0; global_seq = 0
    with evidence_path.open('w') as ef:
        for remote_path in g['trajectories']:
            ap = Path(remote_path).parent.name
            rel = 'job/' + str(Path(remote_path).relative_to(g['job_root']))
            info = fs[rel]; local = raw / rel
            nlines = 0; nonheartbeat = 0
            with local.open() as tf:
                for raw_line, line in enumerate(tf, 1):
                    nlines += 1
                    try:
                        event = json.loads(line)
                    except ValueError as e:
                        parse_errors.append({'raw_path': rel, 'raw_line': raw_line, 'error': str(e)})
                        continue
                    if event.get('type') == 'system' and event.get('subtype') == 'thinking_tokens':
                        heartbeat[ap] += 1
                        continue
                    en += 1; nonheartbeat += 1; global_seq += 1
                    eid = f'{rowname}:T{ap}:L{raw_line:06d}'
                    er = ref(eid, 'evidence.jsonl', en, info, raw_line)
                    kind = event.get('type', 'unknown'); subtype = event.get('subtype')
                    counts[kind + ('.' + subtype if isinstance(subtype, str) else '')] += 1
                    if kind == 'system' and subtype == 'init':
                        init_segment += 1
                        inits.append({'evidence': er, 'attempt': ap, 'init_segment': init_segment, 'tools': event.get('tools'), 'model': event.get('model'), 'session_id': event.get('session_id'), 'claude_code_version': event.get('claude_code_version')})
                    if event.get('session_id'):
                        sessions.add(event['session_id'])
                    flags = {}
                    uid = event.get('uuid')
                    if uid:
                        if uid in seen_uuid: flags['duplicate_uuid_of'] = seen_uuid[uid]
                        else: seen_uuid[uid] = eid
                    # Identical record body is only a candidate replay; do not drop it.
                    payload = {k: v for k, v in event.items() if k not in ['_controller_t', 'uuid']}
                    digest = hashlib.sha256(compact(payload).encode()).hexdigest()
                    if digest in seen_payload: flags['identical_payload_of'] = seen_payload[digest]
                    else: seen_payload[digest] = eid
                    if event.get('isReplay') is not None: flags['isReplay'] = event['isReplay']
                    evidence = {'event_id': eid, 'sequence': global_seq, 'attempt': ap, 'init_segment': init_segment,
                                'observed_at': event.get('_controller_t'), 'source': er, 'replay_flags': flags,
                                'record': strip_private_keys(event)}
                    ef.write(compact(evidence) + '\n')
                    if kind == 'result':
                        result_events.append({'evidence': er, 'attempt': ap, 'subtype': subtype, 'is_error': event.get('is_error'), 'terminal_reason': event.get('terminal_reason'), 'errors': event.get('errors')})
                    if kind == 'system' and (subtype == 'api_retry' or any(x in str(subtype).lower() for x in ['error','fail','compact'])):
                        faults.append({'kind': subtype, 'evidence': er, 'record': strip_private_keys(event)})
                    content = (event.get('message') or {}).get('content', [])
                    if not isinstance(content, list): continue
                    for bi, block in enumerate(content):
                        if not isinstance(block, dict): continue
                        br = dict(er, json_pointer=f'/message/content/{bi}')
                        if block.get('type') == 'tool_use':
                            tid = block.get('id') or f'{eid}:B{bi}'
                            if tid in by_id:
                                old = by_id[tid]
                                old['replayed_call_occurrences'].append(br)
                                if old['input'] != block.get('input') or old['tool_name'] != block.get('name'):
                                    old['conflicting_reuse_of_id'] = True
                                continue
                            name = block.get('name', '')
                            action = {'action_id': f'{rowname}:A{len(actions)+1:05d}', 'order': len(actions)+1,
                                      'tool_use_id': tid, 'tool_name': name, 'canonical_tool': name.removeprefix('mcp__cowork__'),
                                      'attempt': ap, 'init_segment': init_segment, 'session_id': event.get('session_id'),
                                      'call_time': event.get('_controller_t'), 'input': block.get('input'), 'call_evidence': br,
                                      'results': [], 'replayed_call_occurrences': [], 'call_isReplay': event.get('isReplay', False)}
                            by_id[tid] = action; actions.append(action)
                        elif block.get('type') == 'tool_result':
                            tid = block.get('tool_use_id')
                            result = {'evidence': br, 'observed_at': event.get('_controller_t'),
                                      'is_error': block.get('is_error', False), 'content': block.get('content'),
                                      'isReplay': event.get('isReplay', False)}
                            if tid in by_id:
                                action = by_id[tid]
                                result['repeat_result'] = bool(action['results'])
                                action['results'].append(result)
                            else:
                                action = None
                                orphan_results.append({'tool_use_id': tid, **result})
                            if result['is_error']:
                                faults.append({'kind': 'tool_error', 'tool_use_id': tid, 'tool_name': action['tool_name'] if action else None, 'evidence': br})
                            per_result = set()
                            for message in message_ids(block.get('content')):
                                mid = message.get('id') or message.get('message_id')
                                if mid in per_result: continue
                                per_result.add(mid)
                                exposures.append({'message_id': mid, 'first_exposure': mid not in seen_messages,
                                                  'previous_exposure': seen_messages.get(mid), 'action_id': action['action_id'] if action else None,
                                                  'evidence': br, 'message': message})
                                seen_messages.setdefault(mid, br)
            attempt_stats.append({'attempt': ap, 'raw_path': rel, 'raw_sha256': info['sha256'], 'raw_bytes': info['bytes'],
                                  'indexed_bytes': g['indexed_bytes'][remote_path], 'raw_lines': nlines,
                                  'heartbeat_records_filtered': heartbeat[ap], 'evidence_records': nonheartbeat})
    # A returned tool result may occur before its replayed call; report rather than invent a causal order.
    for orphan in orphan_results:
        if orphan['tool_use_id'] in by_id:
            orphan['matching_later_call'] = by_id[orphan['tool_use_id']]['action_id']
    with (out / 'actions.jsonl').open('w') as f:
        for action in actions:
            action['pairing_status'] = 'paired' if action['results'] else 'missing_result'
            # Full result bodies are in evidence; the action index stays small enough to read in full.
            index_action = dict(action)
            index_action['results'] = [{k: v for k, v in r.items() if k != 'content'} for r in action['results']]
            f.write(compact(index_action) + '\n')
    with (out / 'message_exposures.jsonl').open('w') as f:
        for exposure in exposures:
            f.write(compact(exposure) + '\n')
    sidecar_counts = collections.Counter(); runtime_started = []; sidecar_n = 0
    with (out / 'sidecar.jsonl').open('w') as f:
        for rel, info in sorted(fs.items()):
            if '/sidecar-events/' not in rel or not rel.endswith('.jsonl'): continue
            for ln, line in enumerate((raw / rel).open(), 1):
                try: record = json.loads(line)
                except ValueError as e:
                    parse_errors.append({'raw_path': rel, 'raw_line': ln, 'error': str(e)}); continue
                sidecar_n += 1
                eid = f'{rowname}:S{sidecar_n:06d}'
                sr = ref(eid, 'sidecar.jsonl', sidecar_n, info, ln)
                kind = record.get('event') or record.get('type') or record.get('kind') or 'unknown'
                sidecar_counts[str(kind)] += 1
                event = {'event_id': eid, 'source': sr, 'record': strip_private_keys(record)}
                f.write(compact(event) + '\n')
                if kind == 'runtime_started': runtime_started.append(event)
    status = read_json(raw / 'job/STATUS.json', {})
    session = read_json(raw / 'run/session.json', {})
    status_keys = ['run_id','phase','agent_end_reason','agent_completed_normally','failure_category','execution_valid',
                   'tool_calls','agent_elapsed_seconds','started_at','agent_started_at','finished_at','deadline',
                   'retry_count','native_api_retry_counts','outer_retry_wait_seconds','provider_waiting',
                   'last_model_or_tool_progress_at','task_version','task_package_sha256','experiment_fingerprint']
    identity = {k: g['score'][k] for k in ['task_id','task_version','task_package_sha256']}
    identity.update({'row': row, 'host': g['host'], 'run_id': g['run_id'], 'selected_job_root': g['job_root'], 'selected_run_root': g['run_root']})
    instruction = raw / 'run/public/instruction.md'
    # Export submission artifacts only; verifier outcomes remain outside behavior.
    artifact_refs = []
    for basename in ['SOLUTION.md', 'model.patch', 'patch-capture.json']:
        candidates = [(rel, info) for rel, info in fs.items() if Path(rel).name == basename]
        candidates.sort(key=lambda x: (0 if '/capture/' in x[0] else 1, x[0]))
        if candidates:
            rel, info = candidates[0]
            target = out / 'submission' / basename
            target.parent.mkdir(exist_ok=True)
            if target.exists(): target.unlink()
            try: os.link(raw / rel, target)
            except OSError: shutil.copyfile(raw / rel, target)  # cross-device: copy instead of hardlink
            artifact_refs.append({'path': str(target.relative_to(out)), 'raw_path': rel, 'remote_path': info['remote_path'], 'sha256': info['sha256'], 'bytes': info['bytes'], 'kind': 'final_captured_submission'})
    metadata = {'schema': SCHEMA, 'identity': identity,
        'public_instruction': instruction.read_text() if instruction.exists() else None,
        'public_instruction_source': {'raw_path':'run/public/instruction.md','sha256':fs.get('run/public/instruction.md',{}).get('sha256')},
        'runtime': {'status': {k: status.get(k) for k in status_keys if k in status},
                    'binding': strip_private_keys(read_json(raw/'job/RUN_BINDING.json',{})),
                    'initial_state': strip_private_keys(read_json(raw/'job/RUNTIME_STATE_INITIAL.json',{})),
                    'session': strip_private_keys(session), 'runtime_started': runtime_started,
                    'claude_config': strip_private_keys(read_json(raw/'job/CLAUDE_CONFIG.json',{})),
                    'actual_init_segments': inits},
        'counts': {'raw_trajectory_files':len(attempt_stats),'raw_lines':sum(a['raw_lines'] for a in attempt_stats),
                   'filtered_thinking_token_heartbeats':sum(heartbeat.values()),'evidence_records':en,
                   'unique_tool_calls':len(actions),'tool_result_occurrences':sum(len(a['results']) for a in actions),
                   'calls_with_no_result':sum(not a['results'] for a in actions),'replayed_call_occurrences':sum(len(a['replayed_call_occurrences']) for a in actions),
                   'orphan_results':len(orphan_results),'sessions':len(sessions),'init_segments':len(inits),
                   'event_types':dict(counts),'sidecar_records':sidecar_n,'sidecar_event_types':dict(sidecar_counts),
                   'dynamic_message_exposures':len(exposures),'unique_dynamic_messages':len(seen_messages)},
        'attempts':attempt_stats,'session_ids':sorted(sessions),'ends':result_events,'faults':faults,
        'parse_errors':parse_errors,'orphan_tool_results':orphan_results,'submission_artifacts':artifact_refs,
        'files': {'actions.jsonl':'Every unique tool_use in physical attempt order; full input, result evidence references, replay instances. Read all index records.',
                  'evidence.jsonl':'Every non-heartbeat trajectory record without truncation, in original attempt and physical-line order. Source maps to immutable raw and raw line.',
                  'sidecar.jsonl':'All saved sidecar events, including transaction rollback, availability, fact and delivery evidence.',
                  'message_exposures.jsonl':'Dynamic runtime-message bodies actually returned in tool results; repeated IDs marked without treating read=true as reading.'},
        'limitations': ['Only system.thinking_tokens heartbeat records are filtered; original bytes remain immutable outside behavior directory.',
            'isReplay on initial or injected user messages is not assumed to mean duplicate tool execution. Reused tool IDs and identical records are separately flagged.',
            'Tool index has full input and pointers to complete untruncated results in evidence.jsonl; no beginning/end-only trajectory sampling.',
            'Observed controller times, sidecar times, and source-material dates have different meanings. Physical record order is authoritative within each trajectory.',
            'No saved per-request full message arrays are assumed; exposure in a saved transcript does not prove retention after compaction or recovery.',
            'Final submission patch is available for auditing; verifier/grade outcomes and quality-review labels are withheld from behavior inputs.',
            'Dynamic message IDs are scoped to this run; repeated returned messages do not create new notifications or facts.']}
    dump(out/'INPUTS.json', metadata)
    outcome = {'row': row, 'run_id':g['run_id'], 'score_snapshot':g['score'], 'selected_status':status,
               'join_policy':'score_snapshot is authoritative for the current accepted score. Saved original GRADE/result may be superseded by accepted recovery; retain both without silently replacing the selected run.',
               'grade':read_json(raw/'job/GRADE.json'), 'result':read_json(raw/'run/result.json'),
               'diagnostic_raw_files':[f for f in acquisition['files'] if any(t in f['path'].lower() for t in ['grade','reward','verifier','outbound','result'])]}
    dump(rowdir/'outcome.json', outcome)
    input_files = []
    for p in sorted(out.rglob('*')):
        if p.is_file(): input_files.append({'path':str(p.relative_to(out)),'sha256':sha_file(p),'bytes':p.stat().st_size})
    row_manifest = {'row':row,'task_id':identity['task_id'],'run_id':g['run_id'],'input_dir':str(out),
        'schema':SCHEMA,'status':'ready','counts':metadata['counts'],'input_files':input_files,
        'acquisition_manifest':str(raw/'ACQUISITION.json'),'outcome_path':str(rowdir/'outcome.json'),
        'diagnostic_paths':[str(raw),str(rowdir/'outcome.json')],
        'raw_file_count':len(acquisition['files']),'raw_bytes':sum(f['bytes'] for f in acquisition['files']),
        'integrity':{'all_fetched_hashes_verified':True,'all_trajectory_json_parsed':not parse_errors,
                     'all_calls_paired':all(a['results'] for a in actions),'orphan_results':len(orphan_results),
                     'status_run_id_matches':status.get('run_id')==g['run_id'],
                     'status_task_version_matches':status.get('task_version')==identity['task_version'],
                     'status_package_sha_matches':status.get('task_package_sha256')==identity['task_package_sha256']}}
    dump(ROOT/'manifests'/f'{rowname}.json', row_manifest)
    with LOCK:
        refresh_manifest()
        print(json.dumps({'row':row,'status':'ready','actions':len(actions),'evidence_records':en,'sidecar_records':sidecar_n,'raw_bytes':row_manifest['raw_bytes']}),flush=True)
    return row_manifest


def refresh_manifest():
    rows = [read_json(p) for p in sorted((ROOT/'manifests').glob('[0-9][0-9][0-9].json'))]
    dump(ROOT/'manifests/manifest.json', {'schema':SCHEMA,'prepared_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'normalizer':{'path':str(Path(__file__).resolve()),'sha256':sha_file(Path(__file__).resolve())},
        'behavior_corpus_sha256':hashlib.sha256(compact([{'row':r['row'],'run_id':r['run_id'],'input_files':r['input_files']} for r in rows]).encode()).hexdigest(),
        'selection_source':'source-snapshots/CURRENT_SCORES.csv + TRAJECTORY_INDEX.csv selected_for_current_score=True',
        'expected_scored_rows':len(list(csv.DictReader((ROOT/'manifests/source-snapshots/CURRENT_SCORES.csv').open()))),'ready_rows':len(rows),'rows':rows,
        'excluded_rows':[{'row':r,'reason':'excluded_no_current_score'} for r in EXCLUDED],
        'read_policy':'Behavior review reads only each input_dir. diagnostic_paths/outcome_path are controller-only, joined after behavior coding.'})


def prepare_supplements(rows=None):
    """Enrich controller identity/availability evidence without modifying frozen inputs."""
    release=read_json(ROOT/'manifests/source-snapshots/release-MANIFEST.json',{})
    by_row={t['row']:t for t in release.get('tasks',[])}
    summaries=[]
    for p in sorted((ROOT/'manifests').glob('[0-9][0-9][0-9].json')):
        m=read_json(p);row=m['row']
        if rows and row not in rows:continue
        rowdir=ROOT/'inputs'/f'{row:03d}';raw=rowdir/'raw-private'
        inputs=read_json(rowdir/'behavior/INPUTS.json');identity=inputs['identity']
        task=by_row.get(row,{})
        status=read_json(raw/'job/STATUS.json',{})
        runtime_keys=['model','effort','colleague_model','colleague_effort','budget_seconds','scaffold','scaffold_version',
            'runtime_policy_revision','runtime_variant','runtime_tree_sha256','runtime_registry_sha256',
            'provider_errors','last_transport_error','transport_idle_seconds','cleanup_errors']
        observation={'trajectory':'observed' if not inputs['parse_errors'] else 'partially_parseable',
                     'sidecar':'observed' if inputs['counts']['sidecar_records'] else 'not_auditable_no_saved_sidecar_events',
                     'public_instruction':'observed' if inputs['public_instruction'] is not None else 'not_auditable_missing_snapshot',
                     'final_submission_patch':'observed' if any(x['path'].endswith('model.patch') for x in inputs['submission_artifacts']) else 'not_auditable_missing_capture'}
        supplementary={'schema':'behavior-source-supplement-v1','row':row,'run_id':m['run_id'],
            'declared_release':{k:task[k] for k in ['path','baseline','images','language','budget_seconds'] if k in task},
            'release_identity_matches_selected':all(task.get(k)==identity.get(v) for k,v in [('task_id','task_id'),('task_version','task_version'),('source_package_sha256','task_package_sha256')]),
            'runtime_status_metadata':{k:status[k] for k in runtime_keys if k in status},
            'sidecar_budget_patch':strip_private_keys(read_json(raw/'run/sidecar-budget-patch.json',{})),
            'workplace_tool_registry':strip_private_keys(read_json(raw/'run/workplace-tools.json',{})),
            'observation_status':observation,
            'limitations':['Declared release images and saved run/overlay hashes are retained separately; post-cleanup session image lists may be empty. No live image was inspected.',
                'Absent sidecar logs are not a zero count of actual colleague events. Visible tool returns remain independently auditable.',
                'Behavior files and their bound hashes are frozen; this supplement does not change analysis input bytes.',
                'Current score_snapshot is authoritative after accepted recoveries; original GRADE/result can be superseded.']}
        target=rowdir/'metadata-supplement.json';dump(target,supplementary)
        m['metadata_supplement_path']=str(target)
        m['metadata_supplement_sha256']=sha_file(target)
        m['observation_status']=observation
        dump(p,m)
        summaries.append({'row':row,'release_identity_matches_selected':supplementary['release_identity_matches_selected'],**observation})
    refresh_manifest()
    dump(ROOT/'manifests/source-observability.json',summaries)
    summarize_preparation()
    print(json.dumps({'supplements_prepared':len(summaries)}))


def summarize_preparation():
    m=read_json(ROOT/'manifests/manifest.json',{})
    rows=m.get('rows',[])
    expected={int(x['row']) for x in csv.DictReader((ROOT/'manifests/source-snapshots/CURRENT_SCORES.csv').open())}
    total=collections.Counter();missing_results=[];orphans=[];identity_errors=[];size_deltas=[];parse_errors=[]
    for row in rows:
        d=read_json(Path(row['input_dir'])/'INPUTS.json')
        for key in ['raw_trajectory_files','raw_lines','filtered_thinking_token_heartbeats','evidence_records','unique_tool_calls','tool_result_occurrences','calls_with_no_result','replayed_call_occurrences','orphan_results','init_segments','sidecar_records','dynamic_message_exposures','unique_dynamic_messages']:
            total[key]+=d['counts'][key]
        for key in ['status_run_id_matches','status_task_version_matches','status_package_sha_matches']:
            if not row['integrity'].get(key):identity_errors.append({'row':row['row'],'field':key})
        parse_errors.extend({'row':row['row'],**x} for x in d['parse_errors'])
        for a in d['attempts']:
            if a['raw_bytes']!=a['indexed_bytes']:size_deltas.append({'row':row['row'],'attempt':a['attempt'],'raw_bytes':a['raw_bytes'],'indexed_bytes':a['indexed_bytes']})
        for line in (Path(row['input_dir'])/'actions.jsonl').open():
            a=json.loads(line)
            if not a['results']:missing_results.append({'row':row['row'],'action_id':a['action_id'],'tool_use_id':a['tool_use_id'],'tool_name':a['tool_name'],'evidence':a['call_evidence']})
        orphans.extend({'row':row['row'],**x} for x in d['orphan_tool_results'])
    dump(ROOT/'manifests/preparation-summary.json',{
        'schema':SCHEMA,'expected_scored_rows':len(expected),'ready_rows':len(rows),
        'ready_row_ids':[r['row'] for r in rows],'missing_rows':sorted(expected-{r['row'] for r in rows}),
        'excluded_held_rows':list(EXCLUDED),'raw_file_count':sum(r['raw_file_count'] for r in rows),
        'raw_bytes':sum(r['raw_bytes'] for r in rows),'counts':dict(total),
        'rows_without_saved_sidecar':[r['row'] for r in rows if not r['counts']['sidecar_records']],
        'missing_tool_results':missing_results,'orphan_results':orphans,'identity_errors':identity_errors,
        'trajectory_size_deltas_from_frozen_index':size_deltas,'parse_errors':parse_errors,
        'behavior_corpus_sha256':m.get('behavior_corpus_sha256'),
        'method':'All selected attempts; all non-heartbeat records retained without truncation; tool calls paired by ID with replay occurrences retained; behavior and outcomes separated.'})


def prepare_recoveries(rows=None):
    """Preserve accepted recovery evidence separately; never add model trajectories."""
    # Accepted recoveries come from an explicit JSON list (one object per row):
    # {"row": 1, "host": "host-b", "run_id": "...", "job_root": "...", "run_root": "...",
    #  "record": {...accepted-recovery snapshot...}}
    items=read_json(Path(RECOVERIES),[]) if RECOVERIES else []
    records={int(x['row']):x for x in items}
    hosts={h['id']:h for h in read_json(BUNDLE)['hosts']} if BUNDLE else {}
    output=[]
    for row,record in records.items():
        if rows and row not in rows:continue
        run_id=record['run_id'];run_root=record.get('run_root') or record['job_root']+'/no-separate-run'
        spec={'row':row,'host':record.get('host','local'),'run_id':run_id,'job_root':record['job_root'],'run_root':run_root,'trajectories':[],
              'exclude_dirs':['broker','solver-cache','verifier-workspace']}
        record=record.get('record',record)
        acq=acquire(spec,hosts,raw_subdir='accepted-recovery-private')
        rowdir=ROOT/'inputs'/f'{row:03d}'
        snapshot=rowdir/'accepted-recovery-snapshot.json';dump(snapshot,record)
        outcome=read_json(rowdir/'outcome.json')
        if outcome:
            outcome['accepted_recovery_snapshot']=str(snapshot)
            outcome['accepted_recovery_acquisition_manifest']=str(rowdir/'accepted-recovery-private/ACQUISITION.json')
            outcome['join_policy']='score_snapshot is authoritative; accepted recovery is separately preserved and never merged into solver behavior.'
            dump(rowdir/'outcome.json',outcome)
        output.append({'row':row,'source_run_id':record.get('source_run_id'),'recovery_run_id':run_id,
                       'acquisition_manifest':str(rowdir/'accepted-recovery-private/ACQUISITION.json'),
                       'file_count':len(acq['files']),'bytes':sum(f['bytes'] for f in acq['files'])})
        print(json.dumps({'row':row,'accepted_recovery_files':len(acq['files'])}),flush=True)
    dump(ROOT/'manifests/accepted-recoveries.json',output)


def main():
    global ROOT,STATUS,BUNDLE,RELEASE,RECOVERIES,EXCLUDED
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--campaign',type=Path,required=True,help='campaign root to create/resume (inputs/, manifests/)')
    p.add_argument('--status-dir',type=Path,help='dir with CURRENT_SCORES.csv and TRAJECTORY_INDEX.csv')
    p.add_argument('--hosts-bundle',type=Path,help='BUNDLE.json with hosts[].ssh; omit for local trajectories')
    p.add_argument('--bundle',type=Path,required=True,help='public release bundle (MANIFEST.json)')
    p.add_argument('--recoveries',type=Path,help='optional JSON list of accepted recoveries')
    p.add_argument('--excluded-rows',default='',help='comma list of release rows without a scored run')
    p.add_argument('--rows',nargs='*',type=int,help='Default all 99 currently selected scored rows')
    p.add_argument('--workers',type=int,default=2)
    p.add_argument('--normalize-only',action='store_true')
    p.add_argument('--supplement-only',action='store_true',help='Add controller metadata supplements without modifying frozen behavior input files')
    p.add_argument('--recovery-only',action='store_true',help='Read-only acquisition of accepted model-result recovery evidence, separate from behavior')
    p.add_argument('--verify',action='store_true',help='Rehash all saved raw bytes and derived files; no SSH')
    args=p.parse_args()
    ROOT=args.campaign.resolve();STATUS=args.status_dir;BUNDLE=args.hosts_bundle;RELEASE=args.bundle;RECOVERIES=args.recoveries
    EXCLUDED=[int(x) for x in args.excluded_rows.split(',') if x.strip()]
    (ROOT/'manifests').mkdir(parents=True,exist_ok=True)
    if args.recovery_only:
        prepare_recoveries(args.rows);return
    if args.supplement_only:
        prepare_supplements(args.rows);return
    if args.verify:
        manifest=read_json(ROOT/'manifests/manifest.json',{})
        failed=[]; count=0; pairing_errors=[]; audited_actions=0; coverage_errors=[]; audited_raw_records=0; verified_rows=[]
        for f in read_json(ROOT/'manifests/source-snapshot-manifest.json',[]):
            count+=1
            if sha_file(Path(f['snapshot_path']))!=f['sha256']:failed.append(f['snapshot_path'])
        for recovery in read_json(ROOT/'manifests/accepted-recoveries.json',[]):
            if args.rows and recovery['row'] not in args.rows:continue
            acqpath=Path(recovery['acquisition_manifest'])
            for f in read_json(acqpath)['files']:
                count+=1
                if sha_file(acqpath.parent/f['path'])!=f['sha256']:failed.append(str(acqpath.parent/f['path']))
        for row in manifest.get('rows',[]):
            if args.rows and row['row'] not in args.rows: continue
            verified_rows.append(row['row'])
            acq=read_json(Path(row['acquisition_manifest'])); raw=Path(row['acquisition_manifest']).parent
            for f in acq['files']:
                count+=1
                if sha_file(raw/f['path'])!=f['sha256']:failed.append(str(raw/f['path']))
            for f in row['input_files']:
                count+=1
                if sha_file(Path(row['input_dir'])/f['path'])!=f['sha256']:failed.append(str(Path(row['input_dir'])/f['path']))
            basedir=Path(row['input_dir'])
            events=[json.loads(line) for line in (basedir/'evidence.jsonl').open()]
            metadata=read_json(basedir/'INPUTS.json')
            expected_position=0
            for attempt in metadata['attempts']:
                for lineno,line in enumerate((raw/attempt['raw_path']).open(),1):
                    audited_raw_records+=1
                    try:original=json.loads(line)
                    except ValueError:continue
                    if original.get('type')=='system' and original.get('subtype')=='thinking_tokens':continue
                    try:
                        derived=events[expected_position]
                        assert derived['source']['raw_line']==lineno
                        assert derived['source']['raw_path']==attempt['raw_path']
                        assert derived['record']==strip_private_keys(original)
                    except (AssertionError,IndexError,KeyError):coverage_errors.append({'row':row['row'],'raw_path':attempt['raw_path'],'raw_line':lineno})
                    expected_position+=1
            if expected_position!=len(events):coverage_errors.append({'row':row['row'],'reason':'non-heartbeat coverage count mismatch'})
            for line in (basedir/'actions.jsonl').open():
                action=json.loads(line);audited_actions+=1
                for kind,r in [('tool_use',action['call_evidence'])]+[('tool_result',x['evidence']) for x in action['results']]:
                    try:
                        event=events[r['line_start']-1]
                        block=event['record']['message']['content'][int(r['json_pointer'].split('/')[-1])]
                        assert event['event_id']==r['event_id']
                        assert block['type']==kind
                        assert block.get('id',block.get('tool_use_id'))==action['tool_use_id']
                    except (AssertionError,IndexError,KeyError,ValueError):pairing_errors.append({'row':row['row'],'action_id':action['action_id'],'reference':r})
        result={'verified_rows':verified_rows,'verified_files':count,'failed':failed,'audited_actions':audited_actions,'pairing_errors':pairing_errors,
                'audited_raw_records':audited_raw_records,'nonheartbeat_coverage_errors':coverage_errors}
        dump(ROOT/'manifests/verification.json',result)
        print(json.dumps(result));raise SystemExit(bool(failed or pairing_errors or coverage_errors))
    snapshot=source_snapshot(); groups=selection(snapshot)
    hosts={h['id']:h for h in read_json(BUNDLE)['hosts']} if BUNDLE else {}
    order=args.rows or sorted(groups)
    def work(row):
        g=groups[row]
        acq=read_json(ROOT/'inputs'/f'{row:03d}'/'raw-private/ACQUISITION.json') if args.normalize_only else acquire(g,hosts)
        if not acq:raise RuntimeError(f'No raw acquisition for {row}')
        return normalize(g,acq)
    failures=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures={ex.submit(work,row):row for row in order}
        for future in concurrent.futures.as_completed(futures):
            row=futures[future]
            try:future.result()
            except Exception as e:
                failures.append({'row':row,'error':str(e)})
                print(json.dumps({'row':row,'status':'error','error':str(e)}),flush=True)
    dump(ROOT/'manifests/preparation-errors.json',failures)
    if failures:raise SystemExit(1)


if __name__=='__main__':main()
