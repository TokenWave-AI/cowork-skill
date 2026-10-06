#!/usr/bin/env python3
"""Join saved communication IDs without semantic scoring or outcome access.

Adapted for cowork-model-report-skill: ROOT=--campaign, OUT=--out/telemetry/communication;
row-specific narrative removed from the generated report; join logic unchanged."""
import collections
import csv
import datetime
import hashlib
import json
from pathlib import Path
import re

import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from common import config  # noqa: E402
_CFG=config()
OUT=_CFG.comm
ROOT=_CFG.campaign
QUESTION_EVENTS={'question_answered','question_deferred','question_redirected','question_semantic_reply'}
MISSING_SIDECAR=[]
AVAILABILITY={'availability_deferred','availability_followup_counted','availability_opened'}
CARD_RE=re.compile(r'\b[A-Z][A-Z0-9_]{1,20}-[0-9]{2,6}\b')


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def lines(path):
    with path.open() as f:
        for line in f:yield json.loads(line)
def timestamp(value):
    if isinstance(value,(int,float)):return value
    try:return datetime.datetime.fromisoformat(value).timestamp()
    except (TypeError,ValueError):return None
def payloads(content):
    if isinstance(content,dict):yield content
    elif isinstance(content,str):
        try:p=json.loads(content)
        except ValueError:return
        if isinstance(p,dict):yield p
    elif isinstance(content,list):
        for p in content:
            if isinstance(p,dict) and p.get('type')=='text':yield from payloads(p.get('text',''))
def reference(ref,row):
    return {**ref,'path':f'inputs/{row:03d}/behavior/'+ref['path']}
def literal_contains(text,token):
    return bool(re.search(r'(?<![A-Za-z0-9_])'+re.escape(token)+r'(?![A-Za-z0-9_])',text))


def process(item):
    row=item['row'];d=Path(item['input_dir']);meta=json.loads((d/'INPUTS.json').read_text());run=item['run_id']
    for f in item['input_files']:
        assert sha(d/f['path'])==f['sha256'],f'Frozen behavior changed: {row}/{f["path"]}'
    evidence=list(lines(d/'evidence.jsonl'));actions=list(lines(d/'actions.jsonl'));sidecar=list(lines(d/'sidecar.jsonl'))
    exposures=list(lines(d/'message_exposures.jsonl'));actions_by_id={a['action_id']:a for a in actions}
    exposure_by_id=collections.defaultdict(list);visible=[]
    for i,e in enumerate(exposures,1):
        ref=e['evidence'];when=evidence[ref['line_start']-1].get('observed_at')
        v={'row':row,'run_id':run,'message_id':e['message_id'],'action_id':e['action_id'],
           'tool':actions_by_id.get(e['action_id'],{}).get('canonical_tool'),'observed_return_time':when,
           'server_read_bit':e['message'].get('read'),'message_source_at':e['message'].get('at'),
           'author_id':e['message'].get('author_id'),'text':e['message'].get('text'),
           'first_recorded_exposure':e['first_exposure'],'evidence':reference(ref,row),
           'exposure_index_evidence':{'path':f'inputs/{row:03d}/behavior/message_exposures.jsonl','line_start':i,'line_end':i},
           'interpretation':'body returned in saved transcript; read bit is server state, not comprehension'}
        visible.append(v);exposure_by_id[e['message_id']].append(v)
    for values in exposure_by_id.values():values.sort(key=lambda v:(v['evidence']['line_start'],v['evidence'].get('json_pointer','')))
    asks=[];by_qid=collections.defaultdict(list);by_exact=collections.defaultdict(list)
    for action in actions:
        if action['canonical_tool']!='chat_send':continue
        arg=action.get('input') or {};qids=set();replies=set();conversations=set();result_refs=[];error=False
        for result in action['results']:
            ref=result['evidence'];e=evidence[ref['line_start']-1]['record'];block=e['message']['content'][int(ref['json_pointer'].split('/')[-1])]
            result_refs.append(reference(ref,row));error|=bool(block.get('is_error'))
            for payload in payloads(block.get('content')):
                q=payload.get('question');answer=payload.get('reply')
                if isinstance(q,dict) and q.get('id'):qids.add(q['id'])
                if isinstance(answer,dict) and answer.get('id'):replies.add(answer['id'])
                if payload.get('conversation_id'):conversations.add(payload['conversation_id'])
        ask={'row':row,'run_id':run,'action_id':action['action_id'],'tool_use_id':action['tool_use_id'],
             'order':action['order'],'recipient_id':arg.get('recipient_id'),'question_text':arg.get('text'),
             'call_time':action.get('call_time'),'call_evidence':reference(action['call_evidence'],row),
             'return_evidence':result_refs,'return_status':'missing' if not result_refs else 'explicit_is_error' if error else 'no_is_error_flag',
             'question_ids_in_tool_return':sorted(qids),'reply_ids_in_tool_return':sorted(replies),
             'conversation_ids_in_tool_return':sorted(conversations),'sidecar_question_links':[],
             'service_declared_item_actions':[],'declared_fact_ids':[],'fact_disclosure_evidence':[],
             'visible_reply_ids':[],'reply_ids_observed_read_true':[]}
        asks.append(ask)
        for qid in qids:by_qid[qid].append(ask)
        by_exact[(arg.get('recipient_id'),arg.get('text'))].append(ask)
    by_action={a['action_id']:a for a in asks};question_records=[];question_by_id=collections.defaultdict(list)
    questions_side=[s for s in sidecar if s['record'].get('event') in QUESTION_EVENTS]
    exact_side=collections.Counter((s['record'].get('recipient_id'),s['record'].get('text')) for s in questions_side)
    for s in questions_side:
        e=s['record'];qid=e.get('question_id');rid=e.get('reply_id');candidates=by_qid.get(qid,[]);method=None
        if len(candidates)==1:method='question_id_in_tool_return'
        elif not candidates:
            key=(e.get('recipient_id'),e.get('text'))
            if len(by_exact.get(key,[]))==1 and exact_side[key]==1:
                candidates=by_exact[key];method='unique_exact_recipient_and_question_text'
        ask=candidates[0] if method else None
        if ask:
            assert ask['recipient_id']==e.get('recipient_id')
            assert ask['question_text']==e.get('text')
        record={'row':row,'run_id':run,'question_id':qid,'reply_id':rid,'recipient_id':e.get('recipient_id'),
            'conversation_id':e.get('conversation_id'),'sidecar_event':e.get('event'),'sidecar_at':e.get('at'),
            'transaction_committed':e.get('transaction_committed'),'action_id':ask['action_id'] if ask else None,
            'ask_binding':method,'candidate_ask_ids':[a['action_id'] for a in candidates],
            'items':e.get('items',[]),'answered_fact_ids_declared':e.get('answered_fact_ids',[]),
            'newly_disclosed_fact_ids_declared':e.get('newly_disclosed_fact_ids',[]),
            'visible_reply_return_count':len(exposure_by_id.get(rid,[])),
            'first_visible_reply':exposure_by_id.get(rid,[None])[0],
            'first_visible_read_true':next((x for x in exposure_by_id.get(rid,[]) if x['server_read_bit'] is True),None),
            'evidence':reference(s['source'],row),'question_text':e.get('text')}
        question_records.append(record);question_by_id[qid].append(record)
        if ask:
            ask['sidecar_question_links'].append({'question_id':qid,'reply_id':rid,'binding':method,'evidence':record['evidence']})
            ask['service_declared_item_actions'].extend(x.get('action') for x in e.get('items',[]))
            if rid in exposure_by_id:ask['visible_reply_ids'].append(rid)
            if any(x['server_read_bit'] is True for x in exposure_by_id.get(rid,[])):ask['reply_ids_observed_read_true'].append(rid)
    def question_link(qid):
        values=question_by_id.get(qid,[])
        if len(values)==1:return values[0]
        return None
    facts=[];availability=[];unbound=[];chains=collections.defaultdict(list);fact_occurrences=collections.Counter()
    for q in question_records:
        for i,sub in enumerate(q['items']):
            for card in sub.get('card_ids',[]):
                chains[(q['recipient_id'],card)].append({'kind':'question_item','question_id':q['question_id'],
                    'reply_id':q['reply_id'],'action_id':q['action_id'],'item_index':i,'item':sub,
                    'sidecar_at':q['sidecar_at'],'evidence':q['evidence']})
    for s in sidecar:
        e=s['record'];kind=e.get('event');qid=e.get('question_message_id');link=question_link(qid)
        if kind=='fact_disclosed':
            rid=e.get('message_id');exposure=exposure_by_id.get(rid,[])
            fact_occurrences[e.get('fact_id')]+=1
            fact={'row':row,'run_id':run,'fact_id':e.get('fact_id'),'card_id':e.get('card_id'),
                'fact_instance_key':[meta['identity']['task_id'],meta['identity']['task_version'],run,e.get('fact_id')],
                'disclosure_event_ordinal_for_fact':fact_occurrences[e.get('fact_id')],
                'first_disclosure_event_for_fact':fact_occurrences[e.get('fact_id')]==1,
                'module':e.get('module'),'source_ref':e.get('source_ref'),'recipient_id':e.get('recipient_id'),
                'question_id':qid,'reply_id':rid,'transaction_committed':e.get('transaction_committed'),
                'sidecar_at':e.get('at'),'action_id':link['action_id'] if link else None,
                'ask_return_status':by_action[link['action_id']]['return_status'] if link and link['action_id'] else None,
                'question_event_id':link['evidence']['event_id'] if link else None,
                'question_reply_id_agrees':link['reply_id']==rid if link else None,
                'reply_body_visible_in_transcript':bool(exposure),'first_visible_reply':exposure[0] if exposure else None,
                'first_read_true_return':next((x for x in exposure if x['server_read_bit'] is True),None),
                'clarification_rounds_reported':e.get('clarification_rounds'),
                'clarification_measurement':e.get('clarification_measurement'),
                'evidence':reference(s['source'],row),
                'interpretation':'committed program disclosure declaration, with reply-ID exposure link; textual entailment and implementation not evaluated'}
            facts.append(fact)
            chains[(e.get('recipient_id'),e.get('card_id'))].append({'kind':'fact_disclosed','question_id':qid,'reply_id':rid,
                'action_id':fact['action_id'],'fact_id':e.get('fact_id'),'sidecar_at':e.get('at'),'evidence':fact['evidence'],
                'reply_body_visible_in_transcript':bool(exposure)})
            if link and link['action_id']:
                ask=by_action[link['action_id']];ask['declared_fact_ids'].append(e.get('fact_id'));ask['fact_disclosure_evidence'].append(fact['evidence'])
        elif kind in AVAILABILITY:
            rec={'row':row,'run_id':run,'event':kind,'recipient_id':e.get('recipient_id'),'card_id':e.get('card_id'),
                 'question_id':qid,'reply_id':e.get('reply_message_id'),'action_id':link['action_id'] if link else None,
                 'question_event_id':link['evidence']['event_id'] if link else None,'sidecar_at':e.get('at'),
                 'first_defer':e.get('first_defer'),'qualified_followups':e.get('qualified_followups'),
                 'required_followups':e.get('required_followups'),'fixed_followups':e.get('fixed_followups'),
                 'asked_at':e.get('asked_at'),'ready_at':e.get('ready_at'),'evaluated_at':e.get('evaluated_at'),
                 'deadline_reached':e.get('deadline_reached'),'transaction_committed':e.get('transaction_committed'),
                 'evidence':reference(s['source'],row)}
            availability.append(rec);chains[(e.get('recipient_id'),e.get('card_id'))].append({'kind':kind,**rec})
        elif kind in ['colleague_model_failed_closed','conversation_transaction_rolled_back']:
            unbound.append({'row':row,'run_id':run,'event':kind,'sidecar_at':e.get('at'),'recipient_id':e.get('recipient_id'),
                'error_code':e.get('error_code'),'transaction_committed':e.get('transaction_committed'),
                'action_id':None,'binding_status':'no_tool_or_question_id_in_event; no timestamp-only join',
                'evidence':reference(s['source'],row)})
    card_chains=[]
    for (owner,card),records in sorted(chains.items(),key=lambda x:str(x[0])):
        records.sort(key=lambda x:x['evidence']['line_start'])
        qorder=list(dict.fromkeys(x['question_id'] for x in records if x.get('question_id')))
        turns=[]
        for n,qid in enumerate(qorder,1):
            q=question_link(qid);entries=[x for x in records if x.get('question_id')==qid]
            turns.append({'observed_question_ordinal':n,'question_id':qid,'reply_id':q['reply_id'] if q else None,
                'action_id':q['action_id'] if q else None,'records':entries,
                'first_visible_reply':q['first_visible_reply'] if q else None,
                'next_observed_question_id_on_same_owner_card':qorder[n] if n<len(qorder) else None})
        card_chains.append({'row':row,'run_id':run,'recipient_id':owner,'card_id':card,'observed_question_count':len(qorder),
            'turns':turns,'interpretation':'same explicit owner/card chain; ordinal is not necessary clarification depth; next question is not proof it supplied requested missing information'})
    releases=collections.defaultdict(list)
    for s in sidecar:
        if s['record'].get('event')=='delivery_released':releases[s['record']['delivery_id']].append(s)
    notifications=[];visible_delivery_ids=set()
    for mid,values in exposure_by_id.items():
        match=re.fullmatch(r'runtime-(D[0-9]+)-[0-9]+',mid)
        if not match:continue
        did=match.group(1);visible_delivery_ids.add(did);release=releases.get(did,[])
        linked=release[0] if len(release)==1 else None;first=values[0];text=first.get('text') or ''
        cards=sorted(x for x in set(CARD_RE.findall(text)) if not x.startswith(('DOC-','MR-','IU-')))
        direct=[];shared=[]
        for a in actions:
            callref=a['call_evidence']
            if callref['line_start']<=first['evidence']['line_start']:continue
            raw=canonical(a.get('input') or {})
            mention=mid if literal_contains(raw,mid) else None
            if mention:direct.append({'action_id':a['action_id'],'tool':a['canonical_tool'],'matched_message_id':mention,
                'call_time':a.get('call_time'),'call_evidence':reference(callref,row)})
            overlap=[card for card in cards if literal_contains(raw,card)]
            if overlap:shared.append({'action_id':a['action_id'],'tool':a['canonical_tool'],'shared_card_tokens':overlap,
                'call_time':a.get('call_time'),'call_evidence':reference(callref,row),
                'binding':'literal_card_token_cooccurrence_only; not semantic handling or causal response'})
        notifications.append({'row':row,'run_id':run,'message_id':mid,'delivery_id_from_message_format':did,
            'release_link_method':'unique_run_delivery_id_and_runtime_message_prefix' if linked else None,
            'release_evidence':reference(linked['source'],row) if linked else None,
            'release_record':linked['record'] if linked else None,'release_candidate_count':len(release),
            'first_visible_return':first,'visible_return_occurrences':len(values),
            'first_read_true_return':next((x for x in values if x['server_read_bit'] is True),None),
            'notification_card_tokens_in_text':cards,'later_actions_explicitly_mentioning_full_message_id':direct,
            'later_action_literal_card_cooccurrences':shared,
            'handled_or_resolved':None,'new_requirement_or_confirmed_conflict':None,
            'interpretation':'notification exposure and exact lexical links only; no causal, semantic uptake or requirement-change assertion'})
    release_only=[]
    for did,events in releases.items():
        if did not in visible_delivery_ids:
            for s in events:release_only.append({'row':row,'run_id':run,'delivery_id':did,
                'record':s['record'],'evidence':reference(s['source'],row),'visibility':'no_matching_saved_runtime_message_return'})
    for ask in asks:
        for k in ['service_declared_item_actions','declared_fact_ids','visible_reply_ids','reply_ids_observed_read_true']:
            ask[k]=sorted(set(ask[k]))
        ask['declared_fact_disclosure_count']=len(ask['fact_disclosure_evidence'])
        ask['has_linked_committed_fact_declaration']=bool(ask['fact_disclosure_evidence'])
        if not sidecar:
            ask['declared_fact_disclosure_count']=None;ask['has_linked_committed_fact_declaration']=None
        ask['sidecar_observation_status']='available' if sidecar else 'missing; no disclosure-coverage inference'
        ask['interpretation']='attempt and program event links; a no-error chat return is not a fact disclosure or proof of understanding'
    stats={'row':row,'run_id':run,'sidecar_available':bool(sidecar),'ask_attempts':len(asks),
        'asks_with_return_question_id':sum(bool(x['question_ids_in_tool_return']) for x in asks),
        'asks_with_sidecar_question_link':sum(bool(x['sidecar_question_links']) for x in asks),
        'asks_with_fact_declaration':sum(bool(x['has_linked_committed_fact_declaration']) for x in asks),
        'sidecar_question_events':len(question_records),'question_events_linked_to_ask':sum(bool(x['action_id']) for x in question_records),
        'question_events_linked_by_exact_text':sum(x['ask_binding']=='unique_exact_recipient_and_question_text' for x in question_records),
        'question_replies_model_visible':sum(bool(x['visible_reply_return_count']) for x in question_records),
        'declared_fact_events':len(facts),'distinct_declared_fact_ids':len({x['fact_id'] for x in facts}),
        'committed_fact_disclosure_events':sum(x['transaction_committed'] is True for x in facts),
        'repeated_disclosure_events_of_same_fact':sum(not x['first_disclosure_event_for_fact'] for x in facts),
        'fact_events_linked_to_ask':sum(bool(x['action_id']) for x in facts),
        'fact_events_with_visible_reply_id':sum(x['reply_body_visible_in_transcript'] for x in facts),
        'committed_fact_events_with_visible_reply_id':sum(x['transaction_committed'] is True and x['reply_body_visible_in_transcript'] for x in facts),
        'availability_events':len(availability),'availability_events_linked_to_ask':sum(bool(x['action_id']) for x in availability),
        'availability_initial_defer_events':sum(x['event']=='availability_deferred' and x['first_defer'] is True for x in availability),
        'defer_items':sum(i.get('action')=='defer' for x in question_records for i in x['items']),
        'clarify_items':sum(i.get('action')=='clarify' for x in question_records for i in x['items']),
        'unique_visible_notifications':len(notifications),'visible_notifications_with_release_link':sum(bool(x['release_evidence']) for x in notifications),
        'visible_notifications_with_read_true_return':sum(bool(x['first_read_true_return']) for x in notifications),
        'visible_notifications_with_later_exact_message_id_mention':sum(bool(x['later_actions_explicitly_mentioning_full_message_id']) for x in notifications),
        'visible_notifications_with_later_literal_card_cooccurrence':sum(bool(x['later_action_literal_card_cooccurrences']) for x in notifications),
        'released_notifications_without_visible_match':len(release_only),'unbound_failure_and_rollback_events':len(unbound),
        'requirements_acquisition_rate':None,'requirements_acquisition_rate_reason':'no complete independently audited requirement/claim inventory; disclosure IDs are not a requirement denominator'}
    if not sidecar:
        dependent=['asks_with_sidecar_question_link','asks_with_fact_declaration','sidecar_question_events','question_events_linked_to_ask',
            'question_events_linked_by_exact_text','question_replies_model_visible','declared_fact_events','distinct_declared_fact_ids',
            'committed_fact_disclosure_events','repeated_disclosure_events_of_same_fact','fact_events_linked_to_ask',
            'fact_events_with_visible_reply_id','committed_fact_events_with_visible_reply_id','availability_events',
            'availability_events_linked_to_ask','availability_initial_defer_events','defer_items','clarify_items',
            'visible_notifications_with_release_link','released_notifications_without_visible_match','unbound_failure_and_rollback_events']
        for key in dependent:stats[key]=None
    assert len(asks)==sum(a['canonical_tool']=='chat_send' for a in actions)
    assert len(exposures)==meta['counts']['dynamic_message_exposures'] and len(sidecar)==meta['counts']['sidecar_records']
    assert len(facts)==sum(x['record'].get('event')=='fact_disclosed' for x in sidecar)
    return {'ASK_CHAINS':asks,'QUESTION_REPLIES':question_records,'FACT_DISCLOSURES':facts,'AVAILABILITY_EVENTS':availability,
        'CARD_COMMUNICATION_CHAINS':card_chains,'MESSAGE_RETURNS':visible,'NOTIFICATION_CHAINS':notifications,
        'RELEASES_WITHOUT_VISIBLE_RETURN':release_only,'UNBOUND_FAILURE_EVENTS':unbound},stats


def csv_write(path,rows):
    fields=list(dict.fromkeys(k for x in rows for k in x))
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for x in rows:writer.writerow({k:canonical(v) if isinstance(v,(dict,list)) else v for k,v in x.items()})


def flatten_observation(prefix,observation,time_field='observed_return_time',evidence_field='evidence'):
    observation=observation or {};ref=observation.get(evidence_field) or {}
    return {prefix+'_time':observation.get(time_field),prefix+'_action_id':observation.get('action_id'),
        prefix+'_evidence_path':ref.get('path'),prefix+'_evidence_line':ref.get('line_start')}


def compact_csv_rows(key,records):
    # Exclude nested fields across the table, including rows where that object is null.
    nested_fields={k for x in records for k,v in x.items() if isinstance(v,(dict,list))}
    nested_fields.update(['first_visible_reply','first_visible_return','first_read_true_return','release_record'])
    compact=[]
    for lineno,x in enumerate(records,1):
        obj={k:v for k,v in x.items() if k not in nested_fields}
        obj['detail_jsonl']=key+'.jsonl';obj['detail_line']=lineno
        for k in ['call_evidence','evidence','release_evidence']:
            if k in x:obj[k]=x[k]
        if key=='ASK_CHAINS':
            for k in ['question_ids_in_tool_return','reply_ids_in_tool_return','service_declared_item_actions','declared_fact_ids']:obj[k]=x[k]
        if key=='FACT_DISCLOSURES':
            for prefix in ['first_visible_reply','first_read_true_return']:
                obj.update(flatten_observation(prefix,x.get(prefix)))
        if key=='NOTIFICATION_CHAINS':
            for prefix in ['first_visible_return','first_read_true_return']:
                obj.update(flatten_observation(prefix,x.get(prefix)))
            direct=x['later_actions_explicitly_mentioning_full_message_id']
            obj.update(flatten_observation('first_explicit_message_id_reference',direct[0] if direct else None,
                time_field='call_time',evidence_field='call_evidence'))
            obj['explicit_message_id_action_ids']=[a['action_id'] for a in direct]
            obj['explicit_message_id_action_times']=[a['call_time'] for a in direct]
            obj['card_tokens']=x['notification_card_tokens_in_text']
            obj['explicit_message_id_action_count']=len(direct)
            obj['literal_card_candidate_action_count']=len(x['later_action_literal_card_cooccurrences'])
        compact.append(obj)
    return compact


def validate_references(tables):
    references=collections.defaultdict(lambda:collections.defaultdict(set))
    def visit(value):
        if isinstance(value,dict):
            if isinstance(value.get('path'),str) and value.get('line_start'):
                path=value['path'];line=value['line_start']
                assert path.startswith('inputs/') and '/behavior/' in path
                assert line==value.get('line_end')
                references[path][line].add(value.get('event_id'))
            for v in value.values():visit(v)
        elif isinstance(value,list):
            for v in value:visit(v)
    for rows in tables.values():visit(rows)
    errors=[];checked=0
    for path,wanted in references.items():
        seen=set()
        with (ROOT/path).open() as f:
            for lineno,line in enumerate(f,1):
                if lineno not in wanted:continue
                seen.add(lineno);checked+=1;original=json.loads(line)
                for event_id in wanted[lineno]:
                    if event_id is not None and original.get('event_id')!=event_id:
                        errors.append({'path':path,'line':lineno,'expected_event_id':event_id,'actual':original.get('event_id')})
        for missing in set(wanted)-seen:errors.append({'path':path,'missing_line':missing})
    result={'unique_evidence_lines_checked':checked,'source_files_checked':len(references),'errors':errors}
    (OUT/'VALIDATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    assert not errors,errors
    return result


def quality_observations(tables):
    asks={(x['row'],x['action_id']):x for x in tables['ASK_CHAINS']};observations=[]
    for fact in tables['FACT_DISCLOSURES']:
        if fact['transaction_committed'] is not True or fact['reply_body_visible_in_transcript']:continue
        ask=asks.get((fact['row'],fact['action_id']));errors=[];literal_hits=[]
        path=ROOT/f'inputs/{fact["row"]:03d}/behavior/evidence.jsonl'
        result_by_line={r['line_start']:r for r in ask['return_evidence']} if ask else {}
        with path.open() as f:
            for lineno,line in enumerate(f,1):
                if fact['reply_id'] in line:literal_hits.append(lineno)
                if lineno in result_by_line:
                    e=json.loads(line);ref=result_by_line[lineno]
                    block=e['record']['message']['content'][int(ref['json_pointer'].split('/')[-1])]
                    errors.append({'evidence':ref,'is_error':block.get('is_error'),'content':block.get('content')})
        observations.append({'row':fact['row'],'run_id':fact['run_id'],'fact_id':fact['fact_id'],'fact_instance_key':fact['fact_instance_key'],
            'question_id':fact['question_id'],'reply_id':fact['reply_id'],'action_id':fact['action_id'],
            'sidecar_committed_disclosure':True,'sidecar_disclosure_evidence':fact['evidence'],
            'ask_binding_method':next((x['binding'] for x in ask['sidecar_question_links'] if x['question_id']==fact['question_id']),None) if ask else None,
            'ask_call_evidence':ask['call_evidence'] if ask else None,'tool_returns':errors,
            'reply_body_visible_in_saved_transcript':False,'reply_id_literal_search_hits_in_all_evidence_lines':literal_hits,
            'observation_label':'committed_disclosure_without_saved_visible_reply',
            'classification':{'task_defect':None,'runtime_defect':None,'agent_ignored_fact':None},
            'interpretation':'Program-side disclosure committed; linked tool return has an explicit error and no saved reply body. This does not establish a task defect, causal runtime defect or model neglect.'})
    (OUT/'QUALITY_OBSERVATIONS.json').write_text(json.dumps({'schema':'communication-quality-observations-v1',
        'observations':observations,'missing_sidecar_rows':MISSING_SIDECAR,'ground_truth_acquisition_rate':None,
        'fact_counting_rule':'unique (task_id, task_version, run_id, fact_id); repeated events are observations, not additional requirements; notification messages add zero fact instances'},ensure_ascii=False,indent=2)+'\n')
    content=['# 已提交披露但无可见回复：程序观测','',
        '这些记录只描述保存日志之间的差异，不自动判为任务真缺陷、运行器根因或主模型忽略事实。披露事件和正文返回分开统计；缺失覆盖留空。','',
        '| row / fact | 问答 ID / 调用 | 已提交披露证据 | 调用与错误返回证据 |','|---|---|---|---|']
    def cite(ref):
        return f'[{ref["event_id"]}]({ROOT/ref["path"]}:{ref["line_start"]})' if ref else '未绑定'
    for x in observations:
        returns='；'.join(cite(r['evidence']) for r in x['tool_returns'])
        content.append(f'| {x["row"]:03d} / {x["fact_id"]} | {x["question_id"]} → {x["reply_id"]}；{x["action_id"]} | {cite(x["sidecar_disclosure_evidence"])} | {cite(x["ask_call_evidence"])}；{returns} |')
    content+=['','每条sidecar均为transaction_committed=true；对应工具返回is_error=true并带MCP error。对全部evidence.jsonl作回复ID字面检索均未命中；因此只能说没有保存的主模型可见回复正文。ask连接使用唯一recipient_id与完整问题文本，未凭时间邻近配对；错误全文、精确JSON指针、原始文件行号和SHA-256保留在QUALITY_OBSERVATIONS.json。','',
        '事实以(task_id, task_version, run_id, fact_id)去重。FACT_DISCLOSURES另保留同fact的事件序号与首次标记；重复披露不增加独立需求实例。迟到通知不添加事实实例。缺sidecar的run其依赖sidecar的覆盖字段为null/CSV空值，不能当零披露或零机会。缺少全量独立事实真值，因此不计算需求获取率。','']
    (OUT/'QUALITY_OBSERVATIONS.md').write_text('\n'.join(content))
    return observations


def main():
    manifest=json.loads((ROOT/'manifests/manifest.json').read_text());all_tables=collections.defaultdict(list);runs=[]
    for item in sorted(manifest['rows'],key=lambda x:x['row']):
        tables,stats=process(item);runs.append(stats)
        for key,records in tables.items():all_tables[key].extend(records)
    for key,records in all_tables.items():
        with (OUT/(key+'.jsonl')).open('w') as f:
            for record in records:f.write(canonical(record)+'\n')
    global MISSING_SIDECAR
    MISSING_SIDECAR=[x['row'] for x in runs if not x['sidecar_available']]
    for key in ['ASK_CHAINS','FACT_DISCLOSURES','AVAILABILITY_EVENTS','NOTIFICATION_CHAINS']:
        # Compact CSV index: complete nested evidence chains remain in matching JSONL.
        csv_write(OUT/(key+'.csv'),compact_csv_rows(key,all_tables[key]))
    csv_write(OUT/'RUN_COMMUNICATION_COVERAGE.csv',runs)
    validation=validate_references(all_tables)
    observations=quality_observations(all_tables)
    totals={k:sum(x[k] or 0 for x in runs) for k,v in runs[0].items() if isinstance(v,int) and not isinstance(v,bool) and k!='row'}
    summary={'schema':'auditable-communication-chains-v1','rows':len(runs),'behavior_corpus_sha256':manifest['behavior_corpus_sha256'],
        'extractor_sha256':sha(Path(__file__)),'totals':totals,'coverage':{
            'rows_with_sidecar':sum(x['sidecar_available'] for x in runs),'sidecar_missing_rows':[x['row'] for x in runs if not x['sidecar_available']],
            'question_to_ask':{'numerator':totals['question_events_linked_to_ask'],'denominator':totals['sidecar_question_events']},
            'question_reply_visible':{'numerator':totals['question_replies_model_visible'],'denominator':totals['sidecar_question_events']},
            'fact_declaration_reply_visible':{'numerator':totals['fact_events_with_visible_reply_id'],'denominator':totals['declared_fact_events']},
            'notification_release_link':{'numerator':totals['visible_notifications_with_release_link'],'denominator':totals['unique_visible_notifications']}},
        'requirements_acquisition_rate':None,'requirements_acquisition_rate_reason':'no audited complete fact/claim ground truth; not calculated',
        'committed_disclosures_without_visible_reply':[{k:x.get(k) for k in ['row','fact_id','question_id','reply_id','action_id','ask_return_status','evidence']} for x in all_tables['FACT_DISCLOSURES'] if x['transaction_committed'] is True and not x['reply_body_visible_in_transcript']],
        'output_record_counts':{k:len(v) for k,v in all_tables.items()},'checks':{'all_input_hashes_match':True,'all_counts_match_INPUTS':True},
        'reference_validation':validation,
        'quality_observation_count':len(observations),
        'outputs':{p.name:{'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(OUT.iterdir()) if p.suffix in ['.csv','.jsonl']}}
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    note=f'''# 沟通事件链：观测覆盖与口径

覆盖{len(runs)}个选中run；{sum(x['sidecar_available'] for x in runs)}题保存sidecar，缺失：{MISSING_SIDECAR}。冻结behavior文件SHA-256全部复核，未修改输入或原始数据；未读私有分数，未调用模型。本报告只作程序连接，不新增语义或策略评分。

| 可观察连接 | 已连接 / 分母 |
|---|---:|
| sidecar问题事件 → 实际chat_send | {totals['question_events_linked_to_ask']} / {totals['sidecar_question_events']} |
| sidecar回复ID → 转录中实际返回正文 | {totals['question_replies_model_visible']} / {totals['sidecar_question_events']} |
| fact_disclosed回复ID → 转录中实际返回正文 | {totals['fact_events_with_visible_reply_id']} / {totals['declared_fact_events']} |
| 可见通知ID → sidecar delivery_released | {totals['visible_notifications_with_release_link']} / {totals['unique_visible_notifications']} |

共有{totals['ask_attempts']}次chat_send尝试，{totals['asks_with_fact_declaration']}次能连到程序事实披露声明。后一数字不是正确求助率、事实覆盖率或需求获取率：同事可回复公开信息、defer、unknown或多种item，错误/缺返回也必须保留。无完整独立审计的需求claim清单，本次明确不计算需求获取率。

系统记录{totals['defer_items']}个defer item、{totals['clarify_items']}个clarify item；availability另有{totals['availability_initial_defer_events']}个first_defer=true事件。它们不能合并成“必要澄清轮数”。qualified_followups是程序的相关追问计数，observed_question_ordinal只是同owner/card链内问题序号。CARD_COMMUNICATION_CHAINS保留延期、后续问题、门槛打开、披露与返回的原始证据，不推断后续问题是否充分回答澄清，也不把opened自动当成已披露。

**连接强度。** ask首先以返回对象question.id连接sidecar question_id；没有该ID时，仅在双方recipient_id和完整问题文本均唯一且完全相同才连接（本批{totals['question_events_linked_by_exact_text']}条）。recipient和文本均复核。fact及availability以question_message_id连接问题，再以reply/message ID连接实际返回。失败/回滚事件缺少tool/question ID，保留{totals['unbound_failure_and_rollback_events']}条不绑定，不凭时间邻近归到某次并行调用。

**披露与read边界。** fact_disclosed为已提交程序声明，并不是独立证明返回正文完整表达了fact。reply ID出现在tool_result只能证明保存转录中的正文暴露，不证明理解、保留到后续上下文或实现。MESSAGE_RETURNS保留每次正文返回、controller时间、原message.at及read位；read=true只表示服务状态。chat_fetch先标整会话再分页，无法从read位恢复逐条实际阅读。first_read_true_return只计该消息正文实际被返回且read=true的观测。

已提交披露但回复正文未出现在转录中的条目见summary.json committed_disclosures_without_visible_reply；FACT_DISCLOSURES保留其ask_return_status与空可见回复，不把它们计为已得到事实。

上述条目的精确调用/错误返回/sidecar引用及错误全文单列于QUALITY_OBSERVATIONS.md和.json，不自动标为任务或运行器真缺陷，也不归因主模型忽略事实。事实按(task_id, task_version, run_id, fact_id)去重；本批{totals['committed_fact_disclosure_events']}条已提交披露声明对应{totals['distinct_declared_fact_ids']}个run内fact ID，重复事件计数{totals['repeated_disclosure_events_of_same_fact']}。通知不增加事实总数。缺sidecar的run相关覆盖字段留null/CSV空值，汇总仅累计可观察记录并单列缺失题。

**通知连接。** 保存的delivery事件只有delivery_id，没有message_id。唯一同run delivery_id与runtime-DN-序号格式作显式命名规则连接，另保留release候选数与实际消息原文。所核运行器runtime_daemon.py:594–596按source生成runtime-prefix-sequence，1341–1349使用delivery_id作为source；不是仅靠时间近邻。没有sidecar或多个候选时留空。仅见release未见正文的{totals['released_notifications_without_visible_match']}条另表，不称忽略。

{totals['visible_notifications_with_later_exact_message_id_mention']}条可见通知后出现完整message ID的显式工具参数引用；只有这类记录进入直接ID关联列。另有{totals['visible_notifications_with_later_literal_card_cooccurrence']}条在后续工具参数出现相同卡号，保存在独立literal_card_cooccurrence候选列，**不是通知已处理率、语义相关性或因果反应**。卡号从通知文本按大写前缀-数字提取，排除DOC/MR/IU；不等同作者真值目标。没有显式绑定时handled_or_resolved留空。未把迟到导航当新增需求或已证实冲突。

**文件。** ASK_CHAINS逐调用；QUESTION_REPLIES逐sidecar问答与item；FACT_DISCLOSURES逐披露；AVAILABILITY_EVENTS逐程序门槛；CARD_COMMUNICATION_CHAINS按owner/card列出多轮；MESSAGE_RETURNS逐真实正文返回；NOTIFICATION_CHAINS逐去重通知；RELEASES_WITHOUT_VISIBLE_RETURN、UNBOUND_FAILURE_EVENTS保留缺口。ASK_CHAINS、FACT_DISCLOSURES、AVAILABILITY_EVENTS、NOTIFICATION_CHAINS同时提供CSV紧凑索引和完整JSONL；QUESTION_REPLIES、CARD_COMMUNICATION_CHAINS、MESSAGE_RETURNS、RELEASES_WITHOUT_VISIBLE_RETURN、UNBOUND_FAILURE_EVENTS仅提供JSONL（JSONL-only）。RUN_COMMUNICATION_COVERAGE.csv逐题给分母。每条evidence.path相对分析根，line_start/line_end为冻结JSONL物理行，另保留raw_path/raw_line/raw_sha256。所有嵌套正文未首尾截断。

CSV把FACT_DISCLOSURES的first_visible_reply与first_read_true_return展开为各自的_time、_action_id、_evidence_path、_evidence_line列；NOTIFICATION_CHAINS同样展开first_visible_return、first_read_true_return和first_explicit_message_id_reference。返回_time是转录保存的observed_return_time，明确ID引用_time是后续工具调用的call_time，均不取代原消息message.at。通知的explicit_message_id_action_ids与explicit_message_id_action_times为顺序一一对应的JSON数组，保留所有明确ID引用；完整调用证据仍见JSONL。对象列不再因某条记录为null而生成整列空白；展开列空值表示相应观测缺失，read位仍不表示阅读理解。每行detail_jsonl与detail_line指向完整对象；ASK_CHAINS保留call_time供链图连接。

复现：`python3 scripts/run_model_report.py ... --stages telemetry`。summary.json含计数、覆盖率分子分母及输出哈希。

引用验证：已逐一复核{validation['unique_evidence_lines_checked']}个唯一原证据行、{validation['source_files_checked']}个冻结源文件；路径、物理行和event_id均匹配，0错误。详见VALIDATION.json。
'''
    (OUT/'COMMUNICATION_REPORT.md').write_text(note)
    print(json.dumps({'rows':len(runs),'totals':totals,'coverage':summary['coverage']},ensure_ascii=False))


if __name__=='__main__':main()
