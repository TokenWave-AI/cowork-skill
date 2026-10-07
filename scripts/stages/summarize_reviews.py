#!/usr/bin/env python3
"""Aggregate validated blinded annotations, then join the frozen solver outcomes.

Adapted for cowork-model-report-skill: --root is the campaign (manifests/, inputs/); --reviews is the
reviews directory produced by review_runner.py (default OUT/review/reviews); output goes to
OUT/review/summary; also writes OUT/data/stopping.csv (labels only, as the paper's export_extended.py).
Aggregation logic unchanged."""
from collections import Counter
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import sys

sys.dont_write_bytecode = True

LABELS = {
    'search_strategy': '搜索策略', 'decomposition_prioritization': '分解与优先级',
    'hypothesis_testing': '假设求证', 'information_value': '信息价值判断',
    'abstraction_transfer': '抽象与迁移', 'causal_debugging': '因果调试',
    'feedback_adaptation': '反馈适应', 'information_integration': '信息整合',
    'verification_design': '验证设计', 'calibration_stopping': '校准与停止',
    'scope_reconstruction': '工作范围恢复', 'provenance_version_reconciliation': '来源与版本核对',
    'owner_question_followthrough': '提问与跟进', 'notification_handling': '通知处理',
    'evidence_to_implementation': '证据落实代码', 'delivery_accountability': '交付可核性',
}

DAYJOB_LENSES = {
    'premise_scrutiny', 'consequential_prioritization',
    'cross_source_joining', 'evidence_to_decision',
}


def read(path):
    return json.loads(Path(path).read_text())


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def csv_write(path, records, columns):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(records)


def ranks(values):
    order = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        for index in order[start:end]:
            result[index] = (start + end - 1) / 2 + 1
        start = end
    return result


def spearman(pairs):
    if len(pairs) < 3:
        return None
    a, b = (ranks(list(x)) for x in zip(*pairs))
    am, bm = statistics.mean(a), statistics.mean(b)
    numerator = sum((x - am) * (y - bm) for x, y in zip(a, b))
    denominator = math.sqrt(sum((x - am) ** 2 for x in a) * sum((y - bm) ** 2 for y in b))
    return numerator / denominator if denominator else None


def review_usage(root, reviews=None):
    """De-duplicate upstream response IDs across created/completed snapshots."""
    rows = []
    for directory in sorted(((reviews or root / 'reviews') / 'rows').glob('*')):
        responses = {}
        requests = 0
        for path in sorted(directory.glob('attempt-*/upstream-metadata.json')):
            for record in read(path).get('records', []):
                requests += 1
                for response in record.get('responses', []):
                    if response.get('id'):
                        responses.setdefault(response['id'], {}).update(response)
        totals = Counter()
        with_usage = 0
        models = set()
        for response in responses.values():
            if response.get('model'):
                models.add(response['model'])
            usage = response.get('usage')
            if not isinstance(usage, dict):
                continue
            with_usage += 1
            totals['input_tokens'] += usage.get('input_tokens', 0)
            totals['output_tokens'] += usage.get('output_tokens', 0)
            details = usage.get('input_tokens_details') or {}
            totals['cached_input_tokens'] += details.get('cached_tokens', 0)
            totals['cache_write_tokens'] += details.get('cache_write_tokens', 0)
            totals['reasoning_output_tokens'] += (usage.get('output_tokens_details') or {}).get('reasoning_tokens', 0)
        rows.append({'row': directory.name, 'reviewer_models': ','.join(sorted(models)),
                     'http_requests': requests, 'response_ids': len(responses),
                     'responses_with_usage': with_usage, **dict(totals)})
    return rows


def main():
    parser = argparse.ArgumentParser()
    skill_root = Path(__file__).resolve().parents[2]
    parser.add_argument('--root', type=Path, default=Path(os.environ.get('CMR_CAMPAIGN', '.')))
    parser.add_argument('--out', type=Path, default=Path(os.environ.get('CMR_OUT', '.')))
    parser.add_argument('--reviews', type=Path, default=None)
    parser.add_argument('--skill', type=Path, default=skill_root / 'skills/cowork-trajectory-analysis')
    args, _ = parser.parse_known_args()
    root = args.root.resolve()
    reviews = (args.reviews or args.out / 'review' / 'reviews').resolve()
    model = os.environ.get('CMR_MODEL') or 'model' 
    manifest = read(root / 'manifests/manifest.json')
    rows = {int(item['row']): item for item in manifest['rows']}
    spec = importlib.util.spec_from_file_location('report_validator', args.skill / 'scripts/validate_report.py')
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    output = args.out.resolve() / 'review' / 'summary'
    output.mkdir(parents=True, exist_ok=True)
    scheduled = set()
    for path in reviews.glob('BATCH-*.json'):
        scheduled.update(int(row) for row in read(path).get('rows', []))
    states, completed, invalid = Counter(), [], []
    dimension_rows, phase_rows, issue_rows, evidence_rows, tool_rows = [], [], [], [], []
    episode_rows, stop_rows, coverage_rows = [], [], []
    for row, item in sorted(rows.items()):
        directory = reviews / 'rows' / f'{row:03d}'
        if not (directory / 'STATUS.json').exists():
            states['queued_in_controller' if row in scheduled else 'not_scheduled'] += 1
            continue
        status = read(directory / 'STATUS.json')
        state = status['state']
        if state != 'complete':
            states[state] += 1
            continue
        report_path = directory / 'report.json'
        report = read(report_path)
        errors = validator.validate(report, item['input_dir'])
        if status.get('report_sha256') != digest(report_path):
            errors.append('accepted report digest mismatch')
        if not report['coverage']['action_index_fully_examined']:
            errors.append('partial action-index coverage')
        if errors:
            states['invalidated'] += 1
            invalid.append({'row': row, 'errors': errors})
            continue
        states['complete'] += 1
        outcome = read(item['outcome_path'])
        score = outcome['score_snapshot']
        inputs = read(Path(item['input_dir']) / 'INPUTS.json')
        identity = inputs['identity']
        runtime = inputs.get('runtime', {})
        config = runtime.get('claude_config') or {}
        supplement_path = Path(item['input_dir']).parent / 'metadata-supplement.json'
        supplement = read(supplement_path) if supplement_path.exists() else {}
        if supplement and (int(supplement['row']) != row or supplement['run_id'] != identity['run_id']):
            raise ValueError(f'Runtime metadata identity mismatch row {row}')
        runtime_metadata = supplement.get('runtime_status_metadata') or {}
        for name in ('task_id', 'task_version', 'task_package_sha256'):
            if score[name] != identity[name]:
                raise ValueError(f'Outcome identity mismatch row {row} {name}')
        ftotal, ptotal = int(score['f2p_total']), int(score['p2p_total'])
        fpassed, ppassed = int(score['f2p_passed']), int(score['p2p_passed'])
        solver_status = outcome.get('selected_status', {})
        actions = []
        with (Path(item['input_dir']) / 'actions.jsonl').open() as stream:
            for line in stream:
                actions.append(json.loads(line))
        tools = Counter(a.get('canonical_tool', a.get('tool_name', 'unknown')) for a in actions)
        recipients = {a.get('input', {}).get('recipient_id') for a in actions
                      if a.get('canonical_tool') == 'chat_send' and isinstance(a.get('input'), dict)}
        recipients.discard(None)
        for tool_name, count in sorted(tools.items()):
            tool_rows.append({'row': f'{row:03d}', 'run_id': identity['run_id'],
                              'tool': tool_name, 'attempted_calls': count})
        entry = {
            'row': f'{row:03d}', 'run_id': identity['run_id'], 'task_id': identity['task_id'],
            'task_version': identity['task_version'], 'task_package_sha256': identity['task_package_sha256'],
            'solver_model_requested': config.get('model') or runtime_metadata.get('model'),
            'solver_effort_requested': config.get('effort') or runtime_metadata.get('effort'),
            'scaffold': runtime_metadata.get('scaffold') or config.get('harness'),
            'scaffold_version': runtime_metadata.get('scaffold_version'),
            'experiment_condition': (runtime.get('binding') or {}).get('condition'),
            'seed': runtime_metadata.get('seed'),
            'budget_seconds': runtime_metadata.get('budget_seconds'),
            'colleague_model_requested': runtime_metadata.get('colleague_model'),
            'colleague_effort_requested': runtime_metadata.get('colleague_effort'),
            'runtime_policy_revision': runtime_metadata.get('runtime_policy_revision'),
            'runtime_variant': runtime_metadata.get('runtime_variant'),
            'runtime_tree_sha256': runtime_metadata.get('runtime_tree_sha256'),
            'runtime_registry_sha256': runtime_metadata.get('runtime_registry_sha256'),
            'runtime_metadata_source': str(supplement_path) if supplement else None,
            'runtime_metadata_sha256': digest(supplement_path) if supplement else None,
            'f2p_passed': fpassed, 'f2p_total': ftotal, 'f2p_rate': fpassed / ftotal if ftotal else None,
            'p2p_passed': ppassed, 'p2p_total': ptotal, 'p2p_rate': ppassed / ptotal if ptotal else None,
            'solver_category': score['category'], 'preexisting_quality_flag': score['review_flagged'] == 'True',
            'agent_elapsed_seconds': solver_status.get('agent_elapsed_seconds'),
            'tool_calls': len(actions), 'chat_send_attempts': tools['chat_send'],
            'distinct_colleague_recipients_attempted': len(recipients),
            'missing_tool_results': inputs['counts'].get('calls_with_no_result'),
            'runtime_init_segments': inputs['counts'].get('init_segments'),
            'reviewer_models': ','.join(status.get('protocol', {}).get('response_models', [])),
            'strategy_profile': report['summary']['strategy_profile'],
            'ending_type': report['stop_assessment']['ending_type'],
            'premature_stop': report['stop_assessment']['premature_stop'],
            'quality_flag_categories': ','.join(sorted({x['category'] for x in report['quality_flags']})),
            'quality_flag_count': len(report['quality_flags']),
            'evidence_count': len(report['evidence']),
            'report': str(directory / 'report.md'),
        }
        for group in ('strategy_dimensions', 'collaboration_dimensions'):
            for dim in report[group]:
                entry[dim['id'] + '_score'] = dim['score']
                entry[dim['id'] + '_status'] = dim['observation_status']
                dimension_rows.append({'row': entry['row'], 'run_id': identity['run_id'], 'group': group,
                    'dimension': dim['id'], 'label': LABELS[dim['id']], 'score': dim['score'],
                    'observation_status': dim['observation_status'], 'confidence': dim['confidence'],
                    'assessment': dim['assessment'], 'evidence_ids': ','.join(dim['evidence_ids']),
                    'counterevidence_ids': ','.join(dim['counterevidence_ids'])})
        for phase in report['strategy_phases']:
            phase_rows.append({'row': entry['row'], **phase, 'tags': ','.join(phase['tags']), 'evidence_ids': ','.join(phase['evidence_ids'])})
        for episode in report['episodes']:
            episode_rows.append({'row': entry['row'], 'run_id': identity['run_id'],
                'task_version': identity['task_version'], **episode,
                'explicit_dayjob_lens': episode['kind'] if episode['kind'] in DAYJOB_LENSES else '',
                'evidence_ids': ','.join(episode['evidence_ids']),
                'counterevidence_ids': ','.join(episode['counterevidence_ids']),
                'report': entry['report']})
        stop = report['stop_assessment']
        stop_rows.append({'row': entry['row'], 'run_id': identity['run_id'],
            'task_version': identity['task_version'], **stop,
            'evidence_ids': ','.join(stop['evidence_ids']),
            'known_unresolved_items': json.dumps(stop['known_unresolved_items'], ensure_ascii=False),
            'report': entry['report'], 'report_sha256': digest(report_path)})
        coverage = report['coverage']
        coverage_rows.append({'row': entry['row'], 'run_id': identity['run_id'],
            'task_version': identity['task_version'],
            'action_index_fully_examined_self_reported': coverage['action_index_fully_examined'],
            'total_actions': coverage['total_actions'],
            'examined_actions_self_reported': coverage['examined_actions'],
            'detailed_events_examined_self_reported': coverage['detailed_events_examined'],
            'validated_citations': len(report['evidence']),
            'files_examined_self_reported': json.dumps(coverage['files_examined'], ensure_ascii=False),
            'missing_evidence': json.dumps(coverage['missing_evidence'], ensure_ascii=False),
            'coverage_limitations': json.dumps(coverage['limitations'], ensure_ascii=False),
            'report_limitations': json.dumps(report['limitations'], ensure_ascii=False)})
        for flag in report['quality_flags']:
            issue_rows.append({'row': entry['row'], 'run_id': identity['run_id'], **flag,
                              'evidence_ids': ','.join(flag['evidence_ids']), 'report': entry['report']})
        for evidence in report['evidence']:
            evidence_rows.append({'row': entry['row'], 'run_id': identity['run_id'], **evidence,
                                  'input_dir': item['input_dir']})
        completed.append(entry)
    expected = manifest.get('expected_scored_rows', 99)
    if isinstance(expected, list):
        expected = len(expected)
    states['input_not_ready'] = expected - len(rows)
    stats = {}
    for name in LABELS:
        values = [x[name + '_score'] for x in completed if x[name + '_score'] is not None]
        statuses = Counter(x[name + '_status'] for x in completed)
        pairs = [(x[name + '_score'], x['f2p_rate']) for x in completed if x[name + '_score'] is not None and x['f2p_rate'] is not None]
        stats[name] = {'label': LABELS[name], 'rated_tasks': len(values),
            'score_distribution': dict(Counter(values)), 'statuses': dict(statuses),
            'median': statistics.median(values) if values else None,
            'mean_ordinal_score': statistics.mean(values) if values else None,
            'spearman_with_f2p': spearman(pairs), 'association_n': len(pairs)}
    summary = {'generated_at': datetime.now(timezone.utc).isoformat(), 'expected_scored_tasks': expected,
        'input_ready': len(rows), 'scheduled_tasks': len(scheduled), 'validated_reviews': len(completed), 'review_states': dict(states),
        'all_complete': len(completed) == expected, 'invalidated': invalid,
        'dimension_statistics': stats,
        'premature_stop_counts': dict(Counter(x['premature_stop'] for x in completed)),
        'ending_counts': dict(Counter(x['ending_type'] for x in completed)),
        'explicit_dayjob_episode_counts': dict(Counter(x['explicit_dayjob_lens'] for x in episode_rows if x['explicit_dayjob_lens'])),
        'quality_flag_task_counts': dict(Counter(category for x in completed for category in x['quality_flag_categories'].split(',') if category)),
        'limitations': ['Model annotations are not human-validated psychological measurements.',
            'Ordinal dimension scores have separate opportunity-dependent denominators; no aggregate intelligence score.',
            'Associations are exploratory, unadjusted and not causal; task difficulty and runtime faults can confound them.',
            'Behavior annotations exclude private final grades; outcomes are joined only by this script.',
            'Explicit DayJob episode tags index examples, not opportunity-adjusted success rates; missing tags are not negative evidence.',
            'Model-flagged quality concerns do not change original scores or constitute reproduced defects.']}
    write_json(output / 'SUMMARY.json', summary)
    csv_write(output / 'RUN_ANALYSIS.csv', completed, list(completed[0]) if completed else ['row'])
    csv_write(output / 'DIMENSIONS.csv', dimension_rows, ['row','run_id','group','dimension','label','score','observation_status','confidence','assessment','evidence_ids','counterevidence_ids'])
    csv_write(output / 'PHASES.csv', phase_rows, ['row','phase','start_event_id','end_event_id','tags','description','evidence_ids'])
    csv_write(output / 'EPISODES.csv', episode_rows, ['row','run_id','task_version','id','kind','explicit_dayjob_lens','summary',
        'interpretation','evidence_ids','counterevidence_ids','alternative_explanation','confidence','report'])
    csv_write(output / 'STOP_ASSESSMENTS.csv', stop_rows, ['row','run_id','task_version','ending_type','premature_stop',
        'known_unresolved_items','reason','evidence_ids','report','report_sha256'])
    csv_write(output / 'COVERAGE.csv', coverage_rows, ['row','run_id','task_version','action_index_fully_examined_self_reported',
        'total_actions','examined_actions_self_reported','detailed_events_examined_self_reported','validated_citations',
        'files_examined_self_reported','missing_evidence','coverage_limitations','report_limitations'])
    csv_write(output / 'QUALITY_ISSUES.csv', issue_rows, ['row','run_id','category','severity','status','description','scope','potential_impact','check_needed','evidence_ids','report'])
    csv_write(output / 'EVIDENCE.csv', evidence_rows, ['row','run_id','id','path','line_start','line_end','event_id','quote','supports','input_dir'])
    csv_write(output / 'TOOL_BREAKDOWN.csv', tool_rows, ['row','run_id','tool','attempted_calls'])
    usage = review_usage(reviews.parent if reviews.name == 'reviews' else reviews, reviews)
    csv_write(output / 'REVIEWER_USAGE.csv', usage, ['row','reviewer_models','http_requests','response_ids',
        'responses_with_usage','input_tokens','cached_input_tokens','cache_write_tokens','output_tokens','reasoning_output_tokens'])
    lines = [f'# {model} 轨迹分析进度与汇总', '',
        f'更新：{summary["generated_at"]}。Astra xhigh 审查已校验 **{len(completed)}/{expected}** 条。', '',
        '范围：当前有分 CoWork run；016/026 未出分运行不计入此分母。未完成时本文件仅为阶段汇总。', '',
        '过程标注先于分数联结；逐题引用已经程序校验，但能力判断仍是模型标注，尚未经过人类双标。', '',
        '## 状态', '', '| 状态 | 题数 |', '|---|---:|']
    lines += [f'| {name} | {number} |' for name, number in states.items()]
    lines += ['', '## 策略与协作维度', '', '0–3 为有观察证据的等级，缺机会或证据不足留空。各行分母独立；不相加为聪明程度总分。', '',
        '| 维度 | 有评分题数 | 0/1/2/3 分题数 | 中位数 |', '|---|---:|---|---:|']
    for name, stat in stats.items():
        distribution = '/'.join(str(stat['score_distribution'].get(x, 0)) for x in range(4))
        median = str(stat['median']) if stat['median'] is not None else '—'
        lines.append(f'| {stat["label"]} | {stat["rated_tasks"]} | {distribution} | {median} |')
    lines += ['', '## 停止与质量标记', '', '提前停止判断：' + json.dumps(summary['premature_stop_counts'], ensure_ascii=False), '',
        '质量线索涉及题数：' + json.dumps(summary['quality_flag_task_counts'], ensure_ascii=False), '',
        '这些线索需逐条结合证据和必要的复现判断，不自动改分，不把所有后端失败归给主模型。', '',
        '## 逐题入口', '', '| 题号 | F2P | 时长（分钟，含等待） | 停止判断 | 分析 |', '|---|---:|---:|---|---|']
    for item in completed:
        minutes = f'{item["agent_elapsed_seconds"]/60:.1f}' if item['agent_elapsed_seconds'] is not None else '—'
        lines.append(f'| {item["row"]} | {item["f2p_passed"]}/{item["f2p_total"]} | {minutes} | {item["premature_stop"]} | [逐题报告]({item["report"]}) |')
    lines += ['', '结构化文件：RUN_ANALYSIS.csv（逐题与成绩）、DIMENSIONS.csv（各维证据）、PHASES.csv（策略阶段）、EPISODES.csv（关键事件与DayJob视角）、STOP_ASSESSMENTS.csv（停止依据）、COVERAGE.csv（覆盖与缺失）、QUALITY_ISSUES.csv（问题列表）、EVIDENCE.csv（引用索引）。', '',
        'DayJob标签只索引报告中明确标记的案例，未标记不等于没有相关能力或机会，不据此直接计算成功率。覆盖表区分审查模型自报阅读范围与程序已经验证的引用数量。', '',
        'SUMMARY.json 中的 Spearman 仅供探索，不控制任务难度/故障，也没有因果含义。当前不据其作显著性或人类优劣主张。', '']
    (output / 'REPORT.md').write_text('\n'.join(lines))
    data = args.out.resolve() / 'data'
    data.mkdir(parents=True, exist_ok=True)
    csv_write(data / 'stopping.csv', [dict(row=s['row'], ending_type=s['ending_type'], premature_stop=s['premature_stop'],
                                           known_unresolved_items=len(json.loads(s['known_unresolved_items'])))
                                      for s in stop_rows], ['row', 'ending_type', 'premature_stop', 'known_unresolved_items'])
    print(json.dumps({'validated_reviews': len(completed), 'expected': expected, 'states': dict(states), 'report': str(output / 'REPORT.md')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
