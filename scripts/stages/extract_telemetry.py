#!/usr/bin/env python3
"""Objective saved-trace telemetry. No model/API/container calls or behavior edits.

Adapted for cowork-model-report-skill: campaign root and output dir are parameters
(--campaign, --out -> OUT/telemetry); the row count is no longer fixed at 99.  Logic unchanged."""
import collections
import csv
import hashlib
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import config  # noqa: E402
_CFG = config()
ROOT = _CFG.campaign
OUT = _CFG.telemetry
TOKEN_FIELDS = ['input_tokens','cache_creation_input_tokens','cache_read_input_tokens','output_tokens']
RETRIEVAL = {'people','board','docs','chat','reviews','artifacts'}
SEARCHES = {'people_search','board_search','docs_search','chat_search','reviews_search','artifacts_search'}
PRIMARY_COLLEAGUE = {'colleague_reply_rendered','colleague_model_failed_closed'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha_file(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def jsonl(path):
    with path.open() as f:
        for line in f:yield json.loads(line)


def payloads(content):
    """Only transport envelope or entire text JSON; never parse arbitrary body text."""
    if isinstance(content,dict):yield content
    elif isinstance(content,str):
        try:value=json.loads(content)
        except ValueError:return
        if isinstance(value,dict):yield value
    elif isinstance(content,list):
        for block in content:
            if isinstance(block,dict) and block.get('type')=='text':
                yield from payloads(block.get('text',''))


def error_flags(block,tool):
    flags=set()
    if block.get('is_error') is True:flags.add('is_error')
    values=list(payloads(block.get('content')))
    for p in values:
        if p.get('isError') is True or p.get('is_error') is True:flags.add('structured_is_error')
        if p.get('success') is False or p.get('ok') is False:flags.add('structured_false_success')
        if p.get('error') not in (None,False,'',[],{}):flags.add('structured_error')
        if p.get('status') in ['error','failed','failure']:flags.add('structured_failed_status')
        if tool=='terminal' and type(p.get('exit_code')) is int and p['exit_code']!=0:flags.add('terminal_nonzero_exit')
    # Stable transport exception prefixes, not error words inside historic artifacts/logs.
    c=block.get('content')
    texts=[c] if isinstance(c,str) else [b.get('text','') for b in c or [] if isinstance(b,dict)] if isinstance(c,list) else []
    if any(t.lstrip().startswith(('RuntimeError:','Traceback (most recent call last):')) for t in texts if isinstance(t,str)):
        flags.add('transport_exception_prefix')
    return flags,values


def walk_dicts(value):
    if isinstance(value,dict):
        yield value
        for v in value.values():
            if isinstance(v,(dict,list)):yield from walk_dicts(v)
    elif isinstance(value,list):
        for v in value:
            if isinstance(v,(dict,list)):yield from walk_dicts(v)


def surface(tool):
    name=tool.split('_')[0]
    return name if name in RETRIEVAL else None


def returned_entities(tool,values):
    family=surface(tool); ids=set(); bodies=set(); versions=set(); conversations=set()
    if not family:return ids,bodies,versions,conversations
    for payload in values:
        conv=payload.get('conversation')
        if isinstance(conv,dict) and conv.get('id'):conversations.add(str(conv['id']))
        for obj in walk_dicts(payload):
            key=obj.get('key') if family in ['docs','board'] else obj.get('id')
            if isinstance(key,str):
                valid=(family in ['docs','board'] or
                       family=='reviews' and key.startswith('MR-') or
                       family=='artifacts' and 'body' in obj or
                       family=='people' and any(k in obj for k in ['display_name','username','expertise']) or
                       family=='chat' and any(k in obj for k in ['text','body']))
                if valid:
                    ids.add(key)
                    selected=obj.get('selected_version')
                    if 'body' in obj or isinstance(selected,dict) and 'body' in selected:bodies.add(key)
                    if family=='docs' and isinstance(selected,dict) and 'body' in selected:
                        versions.add((key,str(selected.get('version'))))
            if isinstance(obj.get('conversation_id'),str):conversations.add(obj['conversation_id'])
    return ids,bodies,versions,conversations


def numeric_usage(usage):
    return {k:v for k,v in usage.items() if isinstance(v,(int,float)) and not isinstance(v,bool)}


def flatten_usage(usage,prefix=''):
    values={}
    for k,v in usage.items():
        name=prefix+k
        if isinstance(v,dict):values.update(flatten_usage(v,name+'.'))
        elif isinstance(v,(int,float)) and not isinstance(v,bool):values[name]=v
    return values


def union_duration(intervals):
    total=0.0;start=end=None
    for a,b in sorted(intervals):
        if start is None:start,end=a,b
        elif a<=end:end=max(end,b)
        else:total+=end-start;start,end=a,b
    if start is not None:total+=end-start
    return total


def run_one(item):
    row=item['row'];d=Path(item['input_dir']);meta=json.loads((d/'INPUTS.json').read_text())
    for f in item['input_files']:
        if sha_file(d/f['path'])!=f['sha256']:raise ValueError(f'Frozen input hash changed: {row}/{f["path"]}')
    events=list(jsonl(d/'evidence.jsonl'));actions=list(jsonl(d/'actions.jsonl'));sides=list(jsonl(d/'sidecar.jsonl'))
    status=meta['runtime']['status'];identity=meta['identity']
    record={'row':row,'task_id':identity['task_id'],'task_version':identity['task_version'],
        'task_package_sha256':identity['task_package_sha256'],'run_id':identity['run_id'],
        'tool_calls':len(actions),'tool_success_returns':0,'tool_error_calls':0,'tool_missing_return_calls':0,
        'tool_mixed_return_calls':0,'tool_result_occurrences':0,'tool_is_error_calls':0,'tool_content_error_calls':0,
        'chat_send_attempts':0,'chat_send_success_returns':0,'chat_send_error_calls':0,'chat_send_missing_returns':0,
        'agent_elapsed_seconds':status.get('agent_elapsed_seconds'),'agent_end_reason':status.get('agent_end_reason'),
        'outer_retry_wait_seconds_reported':status.get('outer_retry_wait_seconds'),
        'outer_retry_count_reported':status.get('retry_count'),
        'api_retry_count_reported':(status.get('native_api_retry_counts') or {}).get('api_retry',0),
        'api_retry_event_occurrences':0,'api_retry_events_unique':0,'api_retry_backoff_known_seconds':0.0,
        'api_retry_events_missing_delay':0,'attempt_count':len(meta['attempts']),'init_segments':meta['counts']['init_segments'],
        'sidecar_records':len(sides),'sidecar_available':bool(sides),
        'solver_input_tokens':None,'solver_cache_creation_input_tokens':None,'solver_cache_read_input_tokens':None,'solver_output_tokens':None,
        'solver_exact_usage_status':'unknown_full_usage_and_model_usage_differ_or_streams_incomplete',
        'colleague_input_tokens':None,'colleague_output_tokens':None,'colleague_cache_creation_input_tokens':None,
        'colleague_exact_usage_status':'unknown_missing_usage_or_notification_renderer_accounting',
        'solver_assistant_message_events':0,'solver_message_usage_duplicate_observations':0,
        'solver_result_usage_reports':0,'solver_result_usage_model_usage_mismatch_reports':0,
        'colleague_canonical_model_events':0,'colleague_phase_attempts':0,'colleague_phases_with_input_output':0,
        'colleague_phases_missing_input_output':0,'colleague_canonical_duplicate_events_removed':0,
        'colleague_mirrored_phase_records_excluded':0,'colleague_notification_renderer_events':0}
    receipts={'row':row,'run_id':identity['run_id'],'solver_result_reports':[],
              'colleague_usage_events':[],'error_action_evidence':[], 'api_retry_evidence':[],
              'source_ids':{},'input_files_bound':item['input_files']}
    tools={};full_signatures=collections.Counter();query_signatures=collections.Counter();recipients=set()
    attempted=set();returned=set();entity_ids=collections.defaultdict(set);body_ids=collections.defaultdict(set)
    doc_versions=set();chat_conversations=set();intervals=[]
    for a in actions:
        name=a['canonical_tool'];f=surface(name);arg=a.get('input') or {}
        t=tools.setdefault(name,{'row':row,'run_id':identity['run_id'],'tool':name,'calls':0,'success_returns':0,
            'error_calls':0,'missing_returns':0,'mixed_return_calls':0,'is_error_calls':0,'content_error_calls':0,
            'result_occurrences':0,'identical_call_distinct_signatures':0,'identical_call_repeat_occurrences':0,
            'query_calls':0,'query_distinct_strings':0,'identical_query_repeat_occurrences':0,
            'unique_returned_entities':0,'unique_returned_body_entities':0})
        t['calls']+=1
        full_signatures[(name,canonical(arg))]+=1
        if name in SEARCHES:
            query_signatures[(name,canonical(arg.get('query','')))]+=1;t['query_calls']+=1
        if f:attempted.add(f)
        if name=='chat_send':
            record['chat_send_attempts']+=1
            if isinstance(arg.get('recipient_id'),str):recipients.add(arg['recipient_id'])
        results=[];flags=set()
        for result in a['results']:
            er=result['evidence'];event=events[er['line_start']-1]
            block=event['record']['message']['content'][int(er['json_pointer'].split('/')[-1])]
            assert block['tool_use_id']==a['tool_use_id']
            rs,values=error_flags(block,name);flags|=rs;results.append(not rs)
            if not rs and f:
                returned.add(f)
                ids,bodies,versions,convs=returned_entities(name,values)
                entity_ids[name]|=ids;body_ids[name]|=bodies;doc_versions|=versions;chat_conversations|=convs
            start=a.get('call_time');end=result.get('observed_at')
            if isinstance(start,(int,float)) and isinstance(end,(int,float)) and end>=start:
                intervals.append((start,end))
        t['result_occurrences']+=len(results);record['tool_result_occurrences']+=len(results)
        if not results:classification='missing_returns';record['tool_missing_return_calls']+=1
        elif all(results):classification='success_returns';record['tool_success_returns']+=1
        elif not any(results):classification='error_calls';record['tool_error_calls']+=1
        else:classification='mixed_return_calls';record['tool_mixed_return_calls']+=1
        t[classification]+=1
        if 'is_error' in flags:t['is_error_calls']+=1;record['tool_is_error_calls']+=1
        if flags-{'is_error'}:t['content_error_calls']+=1;record['tool_content_error_calls']+=1
        if flags:receipts['error_action_evidence'].append({'action_id':a['action_id'],'tool':name,'flags':sorted(flags),'results':[r['evidence'] for r in a['results']]})
        if name=='chat_send':
            chat_col={'success_returns':'chat_send_success_returns','error_calls':'chat_send_error_calls','missing_returns':'chat_send_missing_returns'}.get(classification)
            if chat_col:record[chat_col]+=1
    for name,t in tools.items():
        sigs=[count for (tool,_),count in full_signatures.items() if tool==name]
        queries=[count for (tool,_),count in query_signatures.items() if tool==name]
        t['identical_call_distinct_signatures']=len(sigs);t['identical_call_repeat_occurrences']=sum(x-1 for x in sigs)
        t['query_distinct_strings']=len(queries);t['identical_query_repeat_occurrences']=sum(x-1 for x in queries)
        t['unique_returned_entities']=len(entity_ids[name]);t['unique_returned_body_entities']=len(body_ids[name])
        assert t['calls']==sum(t[k] for k in ['success_returns','error_calls','missing_returns','mixed_return_calls'])
    record.update({'chat_send_distinct_recipients':len(recipients),'chat_send_recipient_ids':sorted(recipients),
        'retrieval_surface_types_attempted':len(attempted),'retrieval_surface_types_success_returned':len(returned),
        'retrieval_surface_names_attempted':sorted(attempted),'retrieval_surface_names_success_returned':sorted(returned),
        'tool_types_attempted':len(tools),'identical_call_distinct_signatures':len(full_signatures),
        'identical_call_repeat_occurrences':sum(x-1 for x in full_signatures.values()),
        'search_query_calls':sum(query_signatures.values()),'search_query_distinct_tool_strings':len(query_signatures),
        'identical_query_repeat_occurrences':sum(x-1 for x in query_signatures.values()),
        'docs_unique_returned_body_versions':len(doc_versions),'chat_distinct_returned_conversations':len(chat_conversations),
        'tool_observed_intervals_union_seconds':union_duration(intervals),'tool_observed_intervals_sum_seconds':sum(b-a for a,b in intervals)})
    for family in sorted(RETRIEVAL):
        ids=set();bodies=set()
        for name in tools:
            if surface(name)==family:ids|=entity_ids[name];bodies|=body_ids[name]
        record[f'{family}_distinct_returned_entities']=len(ids)
        record[f'{family}_distinct_returned_body_entities']=len(bodies)
        receipts['source_ids'][family]={'entities':sorted(ids),'body_entities':sorted(bodies)}
    exposures=list(jsonl(d/'message_exposures.jsonl'));messages={x['message_id'] for x in exposures}
    record.update({'dynamic_message_return_occurrences':len(exposures),'dynamic_message_ids_unique':len(messages),
        'dynamic_message_repeat_return_occurrences':len(exposures)-len(messages),
        'dynamic_notification_ids_unique':sum(x.startswith('runtime-D') for x in messages),
        'dynamic_answer_ids_unique':sum(x.startswith('runtime-answer-') for x in messages),
        'dynamic_question_ids_unique':sum(x.startswith('runtime-question-') for x in messages)})
    record['dynamic_other_ids_unique']=len(messages)-sum(record[k] for k in ['dynamic_notification_ids_unique','dynamic_answer_ids_unique','dynamic_question_ids_unique'])
    retries=set();message_usage={};result_ids=set();message_refs=collections.defaultdict(list)
    for e in events:
        ev=e['record']
        if ev.get('type')=='system' and ev.get('subtype')=='api_retry':
            record['api_retry_event_occurrences']+=1
            key=ev.get('uuid') or digest(ev)
            if key in retries:continue
            retries.add(key);record['api_retry_events_unique']+=1
            delay=ev.get('retry_delay_ms')
            if isinstance(delay,(int,float)) and not isinstance(delay,bool) and delay>=0:
                record['api_retry_backoff_known_seconds']+=delay/1000
            else:record['api_retry_events_missing_delay']+=1
            receipts['api_retry_evidence'].append({'event_id':e['event_id'],'evidence':e['source'],'delay_ms':delay})
        if ev.get('type')=='assistant':
            msg=ev.get('message') or {};mid=msg.get('id') or ev.get('uuid')
            record['solver_assistant_message_events']+=1
            if mid:
                if mid in message_usage:record['solver_message_usage_duplicate_observations']+=1
                usage=message_usage.setdefault(mid,{})
                for k,v in numeric_usage(msg.get('usage') or {}).items():usage[k]=max(usage.get(k,0),v)
                message_refs[mid].append(e['event_id'])
        if ev.get('type')=='result':
            key=ev.get('uuid') or digest(ev)
            if key in result_ids:continue
            result_ids.add(key);record['solver_result_usage_reports']+=1
            usage=ev.get('usage') or {};models=ev.get('modelUsage') or {}
            mapping={'input_tokens':'inputTokens','output_tokens':'outputTokens','cache_creation_input_tokens':'cacheCreationInputTokens','cache_read_input_tokens':'cacheReadInputTokens'}
            matches=bool(models) and all(usage.get(k)==sum(v.get(m,0) for v in models.values()) for k,m in mapping.items())
            if not matches:record['solver_result_usage_model_usage_mismatch_reports']+=1
            receipts['solver_result_reports'].append({'event_id':e['event_id'],'evidence':e['source'],'attempt':e['attempt'],
                'init_segment':e['init_segment'],'uuid':ev.get('uuid'),'session_id':ev.get('session_id'),
                'usage':usage,'modelUsage':models,'usage_matches_model_usage_components':matches,
                'interpretation':'separate reported invocation snapshots; never added together or claimed full-run billed usage'})
    record['solver_unique_message_ids']=len(message_usage)
    for k in TOKEN_FIELDS:record['solver_observed_message_'+k]=sum(u.get(k,0) for u in message_usage.values())
    # Independent saved harness accounting check; this file contains no grading join.
    metrics_path=d.parent/'raw-private/job/AGENT_METRICS.json'
    metrics=json.loads(metrics_path.read_text()) if metrics_path.exists() else {}
    observed=metrics.get('observed_message_usage') or {}
    record['solver_observed_usage_matches_saved_harness']=all(record['solver_observed_message_'+k]==observed.get(k,0) for k in TOKEN_FIELDS) if observed else None
    if observed:assert record['solver_observed_usage_matches_saved_harness']
    receipts['solver_message_dedup_proof']={'method':'per message.id, maximum observed numeric usage field; matches saved harness implementation; output is incomplete stream observation',
        'unique_message_ids':len(message_usage),'duplicate_message_observations':record['solver_message_usage_duplicate_observations'],
        'message_id_to_event_ids_sha256':digest(message_refs),'message_ids_with_multiple_events':{k:v for k,v in message_refs.items() if len(v)>1}}
    receipts['solver_message_dedup_proof']['saved_harness_comparison']={'path':str(metrics_path),
        'sha256':sha_file(metrics_path) if metrics_path.exists() else None,'matches':record['solver_observed_usage_matches_saved_harness']}
    canonical_seen=set();usage_sums=collections.Counter();usage_coverage=collections.Counter();phase_hashes=[]
    for e in sides:
        event=e['record'];kind=event.get('event');phases=event.get('phase_records') or []
        if kind not in PRIMARY_COLLEAGUE:
            record['colleague_mirrored_phase_records_excluded']+=len(phases);continue
        key=digest(event)
        if key in canonical_seen:record['colleague_canonical_duplicate_events_removed']+=1;continue
        canonical_seen.add(key);record['colleague_canonical_model_events']+=1
        if event.get('mode')=='isolated-model-renderer':record['colleague_notification_renderer_events']+=1
        event_sums=collections.Counter()
        for index,phase in enumerate(phases):
            record['colleague_phase_attempts']+=1;u=flatten_usage(phase.get('usage') or {})
            if all(k in u for k in ['input_tokens','output_tokens']):record['colleague_phases_with_input_output']+=1
            else:record['colleague_phases_missing_input_output']+=1
            usage_sums.update(u);usage_coverage.update(u.keys());event_sums.update(u)
            phase_hashes.append({'event_id':e['event_id'],'phase_index':index,'phase_sha256':digest(phase),
                'prompt_sha256':phase.get('prompt_sha256'),'response_sha256':phase.get('response_sha256')})
        event_usage=flatten_usage(event.get('usage') or {})
        receipts['colleague_usage_events'].append({'event_id':e['event_id'],'evidence':e['source'],'event':kind,
            'mode':event.get('mode'),'phase_count':len(phases),'phase_usage_sum':dict(event_sums),
            'event_usage_aggregate':event_usage,'aggregate_matches_phase_components':dict(event_sums)==event_usage if phases else None,
            'transaction_committed':event.get('transaction_committed')})
    for k in ['input_tokens','output_tokens','total_tokens','cache_creation_input_tokens','cache_read_input_tokens','input_tokens_details.cached_tokens']:
        label=k.replace('.','_')
        record['colleague_observed_phase_'+label]=usage_sums.get(k) if usage_coverage[k] else None
        record['colleague_phases_reporting_'+label]=usage_coverage[k]
    receipts['colleague_phase_dedup_proof']={'method':'use only colleague_reply_rendered and colleague_model_failed_closed; exclude question_* copies; remove only identical canonical parent event JSON; phase index identifies attempt, same prompt/response hash alone does not merge billed requests',
        'phase_receipts':phase_hashes,'unique_canonical_parent_sha256':sorted(canonical_seen),
        'usage_field_coverage':dict(usage_coverage),'units':'tokens; provider input_tokens includes cached input when input_tokens_details is present; cache fields are preserved components, never added to input_tokens'}
    expected=meta['counts']
    assert record['tool_calls']==expected['unique_tool_calls']
    assert record['tool_result_occurrences']==expected['tool_result_occurrences']
    assert record['tool_missing_return_calls']==expected['calls_with_no_result']
    assert len(events)==expected['evidence_records'] and len(sides)==expected['sidecar_records']
    assert len(exposures)==expected['dynamic_message_exposures'] and len(messages)==expected['unique_dynamic_messages']
    assert record['tool_calls']==sum(record[k] for k in ['tool_success_returns','tool_error_calls','tool_missing_return_calls','tool_mixed_return_calls'])
    record['counts_match_inputs']=True
    record['api_retry_event_count_matches_status']=record['api_retry_event_occurrences']==record['api_retry_count_reported']
    receipts['checks']={'counts_match_inputs':True,'input_hashes_match_frozen_manifest':True,
                       'api_retry_event_count_matches_status':record['api_retry_event_count_matches_status']}
    return record,list(tools.values()),receipts


def write_csv(path,rows):
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for row in rows:writer.writerow({k:canonical(v) if isinstance(v,(list,dict)) else v for k,v in row.items()})


def main():
    OUT.mkdir(exist_ok=True)
    manifest=json.loads((ROOT/'manifests/manifest.json').read_text())
    NROWS=len(manifest['rows'])
    runs=[];tools=[];proofs=[]
    for item in sorted(manifest['rows'],key=lambda x:x['row']):
        run,breakdown,proof=run_one(item);runs.append(run);tools.extend(breakdown);proofs.append(proof)
    write_csv(OUT/'RUN_TELEMETRY.csv',runs);write_csv(OUT/'TOOL_BREAKDOWN.csv',tools)
    sums={k:sum(r.get(k) or 0 for r in runs) for k in ['tool_calls','tool_success_returns','tool_error_calls','tool_missing_return_calls',
        'tool_result_occurrences','chat_send_attempts','chat_send_success_returns','chat_send_error_calls','chat_send_missing_returns',
        'api_retry_events_unique','api_retry_backoff_known_seconds','outer_retry_wait_seconds_reported','agent_elapsed_seconds',
        'dynamic_message_return_occurrences','dynamic_message_ids_unique','dynamic_message_repeat_return_occurrences',
        'identical_call_repeat_occurrences','identical_query_repeat_occurrences','colleague_phase_attempts','colleague_phases_missing_input_output',
        'colleague_mirrored_phase_records_excluded']}
    summary={'schema':'objective-trajectory-telemetry-v1','rows':NROWS,'model':_CFG.model,'tool_breakdown_rows':len(tools),
        'behavior_corpus_sha256':manifest['behavior_corpus_sha256'],'extractor_sha256':sha_file(Path(__file__)),
        'totals':sums,'all_counts_match_INPUTS':all(r['counts_match_inputs'] for r in runs),
        'all_observed_message_usage_matches_saved_harness':all(r['solver_observed_usage_matches_saved_harness'] for r in runs),
        'colleague_parent_phase_usage_mismatch_events':sum(e['aggregate_matches_phase_components'] is False for p in proofs for e in p['colleague_usage_events']),
        'api_retry_status_mismatch_rows':[r['row'] for r in runs if not r['api_retry_event_count_matches_status']],
        'known_gaps':{'sidecar_missing_rows':[r['row'] for r in runs if not r['sidecar_available']],
            'missing_tool_returns':{r['row']:r['tool_missing_return_calls'] for r in runs if r['tool_missing_return_calls']}},
        'units':{'times':'seconds','tokens':'provider-reported tokens','counts':'run-scoped occurrences or unique identifiers as named'},
        'no_outcome_read':True,'no_semantic_scoring':True,'per_run_audit':proofs,
        'outputs':{name:{'sha256':sha_file(OUT/name),'bytes':(OUT/name).stat().st_size} for name in ['RUN_TELEMETRY.csv','TOOL_BREAKDOWN.csv']}}
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    notes='''# 客观 telemetry 口径

本表覆盖manifest中全部选中run（数量见summary.json rows）。只读冻结behavior输入；没有读取outcome/F2P/P2P，没有调用模型或启动容器，没有修改behavior。逐题校验冻结文件SHA-256，以及动作、返回、缺返回、动态消息和sidecar数量与INPUTS.json一致。summary.json保留按行审计凭据、原始usage快照与去重证明。

**工具成功与错误。** 每个唯一tool_use_id算一次尝试。success_returns表示至少一个返回且全部没有明确错误标志，并不证明信息有用、事实完整或测试通过。错误依据tool_result.is_error、返回顶层JSON的isError/is_error、success/ok=false、非空error、status=error/failed/failure、terminal非零exit_code，或返回文本开头稳定的RuntimeError/Traceback运输异常。只解析返回的完整JSON envelope，不扫描历史文档/日志正文内的error字样。is_error_calls与content_error_calls可以重叠。缺返回与混合结果另列，四种分类之和等于calls。terminal exit_code=0不表示测试通过；不对命令自然语言分类。

**同事与动态消息。** chat_send尝试数包括失败和缺返回；不同recipient只按实际recipient_id去重，不表示正确owner覆盖。动态消息按每个run内runtime message ID去重；同一返回体重复出现的同ID已在规范化时去重。question、answer、notification分别列示；read位不等于阅读或理解，重复正文暴露不等于新事实。

**来源广度与重复频次。** retrieval surfaces为people/board/docs/chat/reviews/artifacts，分别记录尝试与无明确错误返回的类别数。实体只按实际JSON返回中结构化key/id去重；body字段或selected_version.body出现另计，文档版本按(key,version)去重。搜索snippet/元数据不升级为全文。chat实体数主要是实际返回消息ID，conversation另列。相同调用比较canonical工具名与完整参数JSON（键排序，保持值/大小写/空白）；相同query比较工具名与query字符串，其他filter可以不同。这些仅为raw频次，不标为浪费、冗余或低效。

**时间。** agent_elapsed_seconds、outer_retry_wait_seconds来自冻结INPUTS.runtime.status。API重试按system.api_retry的uuid去重，并单列原始事件数与STATUS计数校验。retry_delay_ms合计是已记录的指定退避，不是全部实际网络等待。工具调用至返回的观察区间同时给出区间并集与简单和；后者有并发重叠，不能当墙钟耗时。以上量不相减，不产生“纯思考时间”，也不把message/source内部日期用于运行时序。

**Solver token。** 精确solver_input/cache/output字段保留空。assistant消息usage按message.id去重，同ID每数值字段取最大，输出为solver_observed_message_*观测分量；这与保存harness的claude_events.py:61–98一致，但流式assistant output usage明显不完整，不能当完整生成量。所有result的usage与modelUsage以uuid去重、逐报告原样保存在summary.per_run_audit.solver_result_reports；不将二者相加，不将usage.iterations再次累加，不用最后一个累计快照代替整个run。两套报告可有差异，且恢复/隐藏CLI调用范围未被独立全量账单证明，因此不生成所谓精确总用量。

**同事 token。** 只从canonical colleague_reply_rendered/colleague_model_failed_closed取phase_records；question_answered/deferred/redirected等镜像phase不再计。完全相同父事件JSON仅计一次；同prompt/response hash不同事件不自动合并。每phase对应一次传输尝试，语义运行器semantic_colleague.py:751–784明确保存该次usage，父事件usage是这些phase的汇总；程序仅累加phase并保存父事件对照，不再加父事件usage。colleague_observed_phase_*是有记录部分的token分量，字段缺失不臆补0；每分量有reporting phase数。缺usage、失败请求可能计费、notification renderer缺用量，故精确全同事总量保留空。Responses input_tokens可能已包含cached input；cache_creation_input_tokens、input_tokens_details.cached_tokens均作为原始分量，不加到input_tokens，不据此推导uncached。单位均为token，非费用。

已知缺口：见summary.json known_gaps（无sidecar的run、缺返回的chat_send）。缺日志不是零交互，缺usage不是零成本。所有统计是可观察程序计数，不新增策略、合作、质量或因果评分。

复现命令：`python3 scripts/run_model_report.py ... --stages telemetry`。输出RUN_TELEMETRY.csv（一题一行）、TOOL_BREAKDOWN.csv（一题一实际工具一行）、summary.json（汇总与审计凭据）。
'''
    (OUT/'TELEMETRY_NOTES.md').write_text(notes)
    print(json.dumps({'rows':NROWS,'tool_breakdown_rows':len(tools),'totals':sums,'all_counts_match_INPUTS':summary['all_counts_match_INPUTS'],
        'api_retry_status_mismatch_rows':summary['api_retry_status_mismatch_rows']},ensure_ascii=False))


if __name__=='__main__':main()
