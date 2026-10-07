#!/usr/bin/env python3
"""Launch one sandboxed, read-only Codex agent and capture its output.

Self-contained replacement for the evaluation pipeline's reviewer_runtime.py (same protocol):
  * private runtime directory with the pinned codex binary, its sandbox alias and bubblewrap;
  * codex exec --ephemeral --ignore-user-config, private CODEX_HOME / TMPDIR / caches per attempt;
  * a named permissions profile: whole filesystem readable except denied roots, the row's own
    attempt directory writable, network disabled for the model's shell;
  * the model's shell gets no inherited environment; the API credential never enters argv or the
    shell (callers pass a per-attempt local token and keep the real key in the controller);
  * logs are redacted and the agent's process group is killed on timeout/cancel.

Configuration (environment, or the review_runner command line):
  CMR_CODEX_BIN     codex binary (also looks for codex-code-mode-host next to it)
  CMR_REVIEW_BASE_URL   upstream Responses API base URL, e.g. https://api.example.com/v1
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import time

CODEX_BIN = Path(os.environ.get('CMR_CODEX_BIN', '') or (shutil.which('codex') or 'codex'))
BASE_URL = os.environ.get('CMR_REVIEW_BASE_URL', '')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def redact(text, *secrets):
    for secret in secrets:
        if secret:
            text = text.replace(secret, '[REDACTED]')
    text = re.sub(r'\b(?:sk|olp|ghp)[-_][A-Za-z0-9_-]{12,}', '[REDACTED]', text)
    return re.sub(r'(?i)Bearer\s+[^\s\"\']+', 'Bearer [REDACTED]', text)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.tmp-{os.getpid()}')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def prepare_runtime(directory, source=None):
    """Private copy of the codex binary (+ code-mode host), sandbox alias and bubblewrap link."""
    source = Path(source or CODEX_BIN).resolve()
    if not source.is_file():
        raise ValueError(f'codex binary not found: {source} (set CMR_CODEX_BIN or --codex-bin)')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    pairs = [(source, directory / 'codex')]
    host = source.parent / 'codex-code-mode-host'
    if host.is_file():
        pairs.append((host, directory / 'codex-code-mode-host'))
    for src, dst in pairs:
        if not dst.exists():
            try:
                os.link(src, dst)
            except FileExistsError:
                pass
            except OSError:
                shutil.copy2(src, dst)
        if digest(src) != digest(dst):
            raise ValueError('private runtime binary does not match the configured codex binary')
    # inherit=none clears Codex's argv0 dispatch PATH; supply the sandbox alias explicitly.
    alias = directory / 'codex-linux-sandbox'
    if not alias.exists():
        try:
            alias.symlink_to('codex')
        except FileExistsError:
            pass
    if alias.resolve() != (directory / 'codex').resolve():
        raise ValueError('unexpected sandbox dispatch alias')
    bwrap_src = shutil.which('bwrap') or '/usr/bin/bwrap'
    resources = directory / 'codex-resources'
    resources.mkdir(exist_ok=True)
    bwrap = resources / 'bwrap'
    if not bwrap.exists():
        try:
            bwrap.symlink_to(bwrap_src)
        except FileExistsError:
            pass
    if not os.access(bwrap, os.X_OK):
        raise ValueError('bubblewrap (bwrap) unavailable; the agent sandbox needs it')
    return directory / 'codex'


def child_environment(attempt, token, key_env='CMR_AGENT_TOKEN'):
    """Environment for the codex process: only basics, private dirs, and the local token."""
    attempt = Path(attempt)
    attempt.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k in {'PATH', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'TERM'}}
    for name, sub in {'HOME': 'home', 'CODEX_HOME': 'codex-home', 'TMPDIR': 'tmp', 'TMP': 'tmp', 'TEMP': 'tmp',
                      'XDG_CACHE_HOME': 'cache', 'XDG_STATE_HOME': 'state',
                      'PYTHONPYCACHEPREFIX': 'cache/pycache'}.items():
        d = attempt / sub
        d.mkdir(parents=True, exist_ok=True)
        env[name] = str(d)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env[key_env] = token
    return env


def deny_except(keep, roots):
    """Paths to deny so that, below each private root, only the `keep` paths (and the directories
    leading to them) stay visible. System directories outside the roots stay readable."""
    keep = [Path(k).resolve() for k in keep]
    out = []

    def walk(directory):
        try:
            children = list(directory.iterdir())
        except OSError:
            return
        for child in children:
            if any(child == k or child.is_relative_to(k) for k in keep):
                continue
            if any(k.is_relative_to(child) for k in keep):
                walk(child)
            else:
                out.append(child)
    for root in roots:
        root = Path(root).resolve()
        if any(root == k or root.is_relative_to(k) for k in keep):
            continue
        if any(k.is_relative_to(root) for k in keep):
            walk(root)
        else:
            out.append(root)
    return out


def build_invocation(attempt, evidence_dir, schema_path, model, effort, *, runtime, base_url, token,
                     retries=3, denied_roots=(), readable_roots=(), key_env='CMR_AGENT_TOKEN'):
    """Return argv/env for one agent; callers must never serialize env (it holds the token)."""
    attempt, evidence_dir, runtime = Path(attempt).resolve(), Path(evidence_dir).resolve(), Path(runtime).resolve()
    env = child_environment(attempt, token, key_env)
    shell_env = {'LANG': env.get('LANG', 'C.UTF-8'), 'TMPDIR': env['TMPDIR'], 'HOME': env['HOME'],
                 'XDG_CACHE_HOME': env['XDG_CACHE_HOME'], 'PYTHONDONTWRITEBYTECODE': '1',
                 'PATH': str(runtime.parent) + ':/usr/local/bin:/usr/bin:/bin'}
    provider = 'cmr_agent'
    config = {
        'model_provider': provider, 'model_reasoning_effort': effort, 'approval_policy': 'never',
        f'model_providers.{provider}.name': 'cowork-model-report agent',
        f'model_providers.{provider}.base_url': base_url,
        f'model_providers.{provider}.env_key': key_env,
        f'model_providers.{provider}.wire_api': 'responses',
        f'model_providers.{provider}.supports_websockets': False,
        f'model_providers.{provider}.request_max_retries': retries,
        f'model_providers.{provider}.stream_max_retries': retries,
        'shell_environment_policy.inherit': 'none',
        'shell_environment_policy.set': shell_env,
        'shell_environment_policy.exclude': [key_env, '*TOKEN*', '*KEY*', '*SECRET*', '*PASSWORD*'],
        'log_dir': str(attempt / 'codex-logs'), 'sqlite_home': str(attempt / 'codex-state'),
        'history.persistence': 'none', 'features.shell_snapshot': False,
        'features.multi_agent': False, 'web_search': 'disabled',
        'default_permissions': 'cmr_isolated',
        'permissions.cmr_isolated.network.enabled': False,
    }
    permissions = {'/': 'read'}
    for path in denied_roots:
        permissions[str(Path(path).resolve())] = 'none'
    for path in [evidence_dir, *readable_roots, runtime.parent]:
        permissions[str(Path(path).resolve())] = 'read'
    permissions[str(attempt)] = 'write'
    # Codex cannot re-open a read/write path inside a denied one: deny siblings, not parents.
    for path, access in permissions.items():
        if access == 'none':
            continue
        for denied in (p for p, a in permissions.items() if a == 'none'):
            if Path(path) == Path(denied) or Path(path).is_relative_to(denied):
                raise ValueError(f'{path} ({access}) lies inside denied {denied}; deny its siblings instead')
    fs_toml = '{' + ','.join(json.dumps(p) + '=' + json.dumps(a) for p, a in permissions.items()) + '}'
    argv = [str(runtime), 'exec', '--strict-config', '--model', model, '--ephemeral', '--ignore-user-config',
            '--ignore-rules', '--skip-git-repo-check', '--enable', 'unified_exec', '--disable', 'multi_agent',
            '--json', '--color', 'never', '--cd', str(evidence_dir), '--output-schema', str(schema_path),
            '--output-last-message', str(attempt / 'review.raw.json'),
            '-c', 'permissions.cmr_isolated.filesystem=' + fs_toml]
    for key, value in config.items():
        if isinstance(value, dict):
            for sub, v in value.items():
                argv += ['-c', f'{key}.{sub}=' + json.dumps(v)]
        else:
            argv += ['-c', f'{key}=' + json.dumps(value)]
    return argv + ['-'], env


def invoke_reviewer(argv, env, prompt, attempt, timeout_seconds=7200, cancel_event=None, secrets=()):
    """Run one agent; stream redacted logs; kill only its own process group."""
    attempt = Path(attempt)
    secrets = tuple(secrets) + tuple(v for k, v in env.items() if 'TOKEN' in k or 'KEY' in k)
    started = time.monotonic()
    selector = selectors.DefaultSelector()
    pending = {'stdout': b'', 'stderr': b''}
    files = {}
    reason, total, heartbeat = None, 0, started
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               cwd=attempt, env=env, start_new_session=True)
    started_at = time.time()
    try:
        write_json(attempt / 'heartbeat.json', {'pid': process.pid, 'started_at_epoch': started_at,
                                                'updated_at_epoch': started_at, 'elapsed_seconds': 0, 'status': 'reviewing'})
        selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
        selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
        files['stdout'] = (attempt / 'events.jsonl').open('w')
        files['stderr'] = (attempt / 'stderr.log').open('w')
        process.stdin.write(prompt.encode())
        process.stdin.close()
        while selector.get_map():
            if cancel_event is not None and cancel_event.is_set():
                reason = 'review_cancelled'
                break
            if time.monotonic() - started >= timeout_seconds:
                reason = 'review_timeout'
                break
            if total > 128 * 1024 * 1024:
                reason = 'review_log_limit'
                break
            for key, _ in selector.select(timeout=1):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                total += len(chunk)
                pending[key.data] += chunk
                while b'\n' in pending[key.data]:
                    line, pending[key.data] = pending[key.data].split(b'\n', 1)
                    files[key.data].write(redact(line.decode(errors='replace'), *secrets) + '\n')
                    files[key.data].flush()
            if time.monotonic() - heartbeat >= 30:
                write_json(attempt / 'heartbeat.json', {'pid': process.pid, 'started_at_epoch': started_at,
                                                        'updated_at_epoch': time.time(),
                                                        'elapsed_seconds': round(time.monotonic() - started),
                                                        'status': 'reviewing'})
                heartbeat = time.monotonic()
    except BaseException:
        reason = reason or 'review_interrupted'
        raise
    finally:
        def signal_group(sig):
            try:
                os.killpg(process.pid, sig)
                return True
            except ProcessLookupError:
                return False
        if reason:
            signal_group(signal.SIGTERM)
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                reason = reason or 'review_exit_timeout'
                signal_group(signal.SIGKILL)
                process.wait(timeout=5)
        if signal_group(0):
            signal_group(signal.SIGKILL)
        selector.close()
        for name, stream in files.items():
            if pending[name]:
                stream.write(redact(pending[name].decode(errors='replace'), *secrets))
            stream.close()
        if not process.stdin.closed:
            try:
                process.stdin.close()
            except BrokenPipeError:
                pass
        process.stdout.close()
        process.stderr.close()
        raw = attempt / 'review.raw.json'
        if raw.exists():
            raw.write_text(redact(raw.read_text(), *secrets))
        write_json(attempt / 'heartbeat.json', {'pid': process.pid, 'started_at_epoch': started_at,
                                                'updated_at_epoch': time.time(),
                                                'elapsed_seconds': round(time.monotonic() - started),
                                                'status': 'stopped', 'reason': reason, 'returncode': process.returncode})
    return {'returncode': process.returncode, 'reason': reason,
            'wall_seconds': round(time.monotonic() - started, 3), 'timeout_seconds': timeout_seconds}
