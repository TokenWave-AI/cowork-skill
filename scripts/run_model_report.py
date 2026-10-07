#!/usr/bin/env python3
"""Per-model SWE-CoWork trajectory report: single entry point.

    python3 scripts/run_model_report.py --model NAME --campaign DIR --bundle DIR --out DIR \
        [--package DIR] [--stages prepare,telemetry,nodes,collab,basics,review,stats,report] \
        [--claims-blind-check CSV] [--force]

Stages (default: telemetry,nodes,collab,basics,review-merge,dossier,stats,report; i.e. everything that needs
no network and no LLM):
  prepare       (a) acquire + normalise trajectories into CAMPAIGN/inputs/NNN/{behavior,raw-private,outcome.json}
                    -- only when the campaign is not prepared yet; needs --prepare-args (see SKILL.md)
  telemetry     (b) objective telemetry + communication chains           -> OUT/telemetry/
  nodes         (c) runs.csv, per-node outcomes, reconciliation           -> OUT/data/{runs,NODE_OUTCOMES,RECONCILE}.csv
  collab        (d) collaboration metrics, loss attribution, export      -> OUT/data/{COLLAB_*,ATTRIBUTION,requirements,f2p_nodes,collaboration_runs}.csv
  basics        (e) delivery claims strict+broad, deferrals, question timing, rule compliance
  review        (f) LLM rubric review (gpt-6-astra/xhigh via the 1.2 skill); costs money, see SKILL.md.
                    Runs review_runner.py, then summarize.
  review-merge  (f') summarize already-completed reviews (OUT/review/reviews or --reviews DIR) -> stopping.csv
  diagnose      (i) round-2 agents: one codex per run with outcomes + spec -> OUT/diagnosis/rows/NNN/report.json
                    (builds OUT/diagnosis/context first; run after review-merge + dossier)
  diagnose-merge (i') summarize diagnoses -> OUT/diagnosis/summary/, consumed by stats/report
  dossier       (h) per-run dossiers: full conversations, transcript, requirement/node tables,
                    patch, delivery note, reviewer report -> OUT/runs/NNN/, OUT/data/RUN_SUMMARY.csv
  stats         (g) statistics.json
  report        (g) paper_rows.tex, tables/, figures/*.pdf, report.md

Every stage is idempotent and resumable: re-run the same command; finished stages are skipped
unless --force (stage outputs are listed in STAGE_OUTPUTS).  A run log is appended to OUT/RUNLOG.jsonl.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import Config, DEFAULT_PACKAGE  # noqa: E402

S = HERE / 'stages'
PY = sys.executable
# Interpreter for the review stages: needs jsonschema>=4 (Draft202012Validator).
# Set with --review-python or env CMR_REVIEW_PYTHON; falls back to this interpreter.
REVIEW_PY_DEFAULT = os.environ.get('CMR_REVIEW_PYTHON', '')


def review_python(a):
    if a.review_python:
        return a.review_python
    return REVIEW_PY_DEFAULT if REVIEW_PY_DEFAULT and Path(REVIEW_PY_DEFAULT).exists() else PY

STAGE_OUTPUTS = {
    'telemetry': ['telemetry/RUN_TELEMETRY.csv', 'telemetry/communication/ASK_CHAINS.jsonl',
                  'telemetry/communication/FACT_DISCLOSURES.csv', 'telemetry/communication/AVAILABILITY_EVENTS.jsonl'],
    'nodes': ['data/runs.csv', 'data/NODE_OUTCOMES.csv', 'data/RECONCILE.csv'],
    'collab': ['data/COLLAB_RUNS.csv', 'data/ATTRIBUTION.csv', 'data/requirements.csv', 'data/f2p_nodes.csv',
               'data/collaboration_runs.csv'],
    'basics': ['data/delivery_claims.csv', 'data/delivery_claims_broad.csv', 'data/deferrals.csv',
               'data/question_deciles.json', 'data/workplace_basics_runs.csv'],
    'review': ['review/summary/RUN_ANALYSIS.csv', 'data/stopping.csv'],
    'review-merge': ['review/summary/RUN_ANALYSIS.csv', 'data/stopping.csv'],
    'dossier': ['runs/INDEX.md', 'data/RUN_SUMMARY.csv'],
    'diagnose': ['diagnosis/summary/DIAGNOSES.csv'],
    'diagnose-merge': ['diagnosis/summary/DIAGNOSES.csv'],
    'stats': ['statistics.json'],
    'report': ['report.md', 'paper_rows.tex'],
}
DEFAULT = ['telemetry', 'nodes', 'collab', 'basics', 'review-merge', 'dossier', 'stats', 'report']
ORDER = ['prepare', 'telemetry', 'nodes', 'collab', 'basics', 'review', 'review-merge', 'dossier', 'diagnose',
         'diagnose-merge', 'stats', 'report']


def run(cmd, cfg, log, env_extra=None):
    env = cfg.env()
    env['MPLCONFIGDIR'] = str(cfg.out / '.cache' / 'matplotlib')
    if env_extra:
        env.update(env_extra)
    t = time.time()
    print('  $', ' '.join(str(c) for c in cmd), flush=True)
    p = subprocess.run([str(c) for c in cmd], env=env, cwd=str(HERE), capture_output=True, text=True)
    tail = (p.stdout[-1500:] + ('\n' + p.stderr[-3000:] if p.returncode else ''))
    print('    ' + tail.strip().replace('\n', '\n    '), flush=True)
    log.append(dict(cmd=[str(c) for c in cmd], rc=p.returncode, seconds=round(time.time() - t, 1)))
    if p.returncode:
        raise SystemExit(f'stage command failed (rc={p.returncode}): {cmd[1]}')


def stage_cmds(name, cfg, a):
    c = []
    if name == 'prepare':
        if not a.prepare_args:
            raise SystemExit('prepare: pass --prepare-args "--status-dir DIR [--hosts-bundle JSON] [--recoveries JSON] '
                             '[--excluded-rows 16,26]" (see SKILL.md, stage a)')
        base = [PY, S / 'prepare_inputs.py', '--campaign', cfg.campaign, '--bundle', cfg.bundle] + a.prepare_args.split()
        c += [base, base + ['--supplement-only']]
        if '--recoveries' in a.prepare_args:
            c.append(base + ['--recovery-only'])
    elif name == 'telemetry':
        c += [[PY, S / 'extract_telemetry.py'], [PY, S / 'extract_communication.py']]
    elif name == 'nodes':
        c += [[PY, S / 'build_runs.py'], [PY, S / 'build_node_outcomes.py']]
    elif name == 'collab':
        c += [[PY, S / 'collab_metrics.py'], [PY, S / 'attribution.py'], [PY, S / 'export_extended.py']]
    elif name == 'basics':
        c += [[PY, S / 'build_claims.py'], ('CLAIMS_BROAD', [PY, S / 'build_claims.py']),
              [PY, S / 'build_workplace_basics.py']]
    elif name == 'review':
        skill = HERE.parent / 'skills' / 'cowork-trajectory-analysis'
        rpy = review_python(a)
        cmd = [rpy, '-B', S / 'review_runner.py', '--inputs-manifest', cfg.manifest_path, '--skill', skill,
               '--schema', skill / 'references' / 'output.schema.json', '--output', cfg.review / 'reviews',
               '--concurrency', str(a.review_concurrency)]
        if a.review_rows:
            cmd += ['--rows', a.review_rows]
        if a.review_dry_run:
            cmd += ['--dry-run']
        c += [('ALLOW_FAIL', cmd)]
        c += [[rpy, S / 'summarize_reviews.py'] + (['--reviews', a.reviews] if a.reviews else [])]
    elif name == 'review-merge':
        src = Path(a.reviews) if a.reviews else cfg.review / 'reviews'
        if not (src / 'rows').is_dir():
            print('  review-merge: no reviews at', src, '-> report will omit rubric/stopping sections')
            return []
        c += [[review_python(a), S / 'summarize_reviews.py', '--reviews', src]]
    elif name in ('diagnose', 'diagnose-merge'):
        reviews = a.reviews or str(cfg.review / 'reviews')
        if name == 'diagnose':
            skill = HERE.parent / 'skills' / 'cowork-failure-diagnosis'
            rpy = review_python(a)
            c += [[PY, S / 'build_diagnosis_context.py', '--reviews', reviews]]
            cmd = [rpy, '-B', S / 'review_runner.py', '--phase', 'diagnosis', '--inputs-manifest', cfg.manifest_path,
                   '--skill', skill, '--schema', skill / 'references' / 'output.schema.json',
                   '--context-root', cfg.out / 'diagnosis' / 'context', '--output', cfg.out / 'diagnosis',
                   '--concurrency', str(a.review_concurrency)]
            if a.review_rows:
                cmd += ['--rows', a.review_rows]
            if a.review_dry_run:
                cmd += ['--dry-run']
            c += [('ALLOW_FAIL', cmd)]
        c += [[review_python(a), S / 'summarize_diagnoses.py']]
    elif name == 'dossier':
        c += [[PY, S / 'build_dossiers.py', '--dossier-result-chars', str(a.dossier_result_chars)]]
    elif name == 'stats':
        cmd = [PY, S / 'compute_statistics.py']
        if a.claims_blind_check:
            cmd += ['--claims-blind-check', a.claims_blind_check]
        c.append(cmd)
    elif name == 'report':
        c += [[PY, HERE / 'make_report.py']]
    return c


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--model', required=True, help='display name, e.g. "Opus-5.5"')
    p.add_argument('--campaign', required=True, help='campaign root with manifests/manifest.json and inputs/NNN/')
    p.add_argument('--bundle', required=True, help='public benchmark bundle (MANIFEST.json, tasks/, oracle/)')
    p.add_argument('--out', required=True)
    p.add_argument('--package', default=str(DEFAULT_PACKAGE),
                   help='package-level data: requirement_links/NNN.json + release101_tasks.json')
    p.add_argument('--stages', default=','.join(DEFAULT))
    p.add_argument('--force', action='store_true', help='re-run stages whose outputs already exist')
    p.add_argument('--claims-blind-check', help='optional CSV (row,card_id,verdict,quote) from a blind reader')
    p.add_argument('--reviews', help='existing reviews dir (with rows/NNN/report.json) to merge')
    p.add_argument('--prepare-args', default='', help='extra args for stages/prepare_inputs.py')
    p.add_argument('--review-concurrency', type=int, default=20)
    p.add_argument('--review-rows', default='')
    p.add_argument('--review-dry-run', action='store_true')
    p.add_argument('--review-python', default='')
    p.add_argument('--dossier-result-chars', type=int, default=0,
                   help='tool results longer than this are clipped (head+tail) in runs/NNN/transcript.md; 0 = keep all')
    a = p.parse_args()
    for k in ('claims_blind_check', 'reviews'):
        if getattr(a, k):
            setattr(a, k, str(Path(getattr(a, k)).resolve()))
    cfg = Config(a.model, a.campaign, a.bundle, a.out, a.package)
    cfg.out.mkdir(parents=True, exist_ok=True)
    stages = [s.strip() for s in a.stages.split(',') if s.strip()]
    bad = [s for s in stages if s not in ORDER]
    if bad:
        raise SystemExit(f'unknown stage(s) {bad}; choose from {ORDER}')
    stages.sort(key=ORDER.index)
    if not cfg.links.is_dir() or not cfg.release_tasks.exists():
        raise SystemExit(f'package data missing under {cfg.package}: need requirement_links/NNN.json and '
                         'release101_tasks.json (internal data package, not in the public repo; pass --package DIR)')
    if 'prepare' not in stages and not cfg.manifest_path.exists():
        raise SystemExit(f'{cfg.manifest_path} missing: run --stages prepare first (SKILL.md stage a)')
    (cfg.out / 'CONFIG.json').write_text(json.dumps(dict(model=cfg.model, campaign=str(cfg.campaign),
                                                         bundle=str(cfg.bundle), package=str(cfg.package)), indent=1) + '\n')
    log = []
    t_all = time.time()
    for s in stages:
        outs = STAGE_OUTPUTS.get(s, [])
        if outs and not a.force and all((cfg.out / o).exists() for o in outs) and s in ('telemetry', 'nodes', 'collab', 'basics'):
            print(f'[{s}] up to date (use --force to rebuild)')
            continue
        print(f'[{s}]', flush=True)
        t = time.time()
        for cmd in stage_cmds(s, cfg, a):
            if isinstance(cmd, tuple):
                tag, cmd = cmd
                if tag == 'CLAIMS_BROAD':
                    run(cmd, cfg, log, {'CLAIMS_BROAD': '1'})
                    continue
                if tag == 'ALLOW_FAIL':
                    try:
                        run(cmd, cfg, log)
                    except SystemExit as e:
                        print('  review runner did not complete every row:', e, '-- summarising completed rows')
                    continue
            run(cmd, cfg, log)
        print(f'[{s}] done in {time.time() - t:.0f}s', flush=True)
    with open(cfg.out / 'RUNLOG.jsonl', 'a') as f:
        f.write(json.dumps(dict(at=time.strftime('%Y-%m-%dT%H:%M:%S'), stages=stages,
                                seconds=round(time.time() - t_all, 1), commands=log)) + '\n')
    print(f'all requested stages finished in {time.time() - t_all:.0f}s -> {cfg.out}')


if __name__ == '__main__':
    main()
