"""Evaluation checkpoints and compatibility checks for safe, in-place resume."""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from . import harbor
from .tasks import attempt_from_trial, score


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError('expected JSON objects')
        return rows
    except (ValueError, OSError) as error:
        raise ValueError(f'cannot resume: invalid checkpoint {path}: {error}') from error


def append_row(path: Path, row: dict) -> None:
    with path.open('a', encoding='utf-8') as file:
        file.write(json.dumps(row, ensure_ascii=False) + '\n')
        file.flush()
        os.fsync(file.fileno())


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, default=str) + '\n')
    temporary.replace(path)


@contextmanager
def run_lock(out: Path):
    # flock releases automatically even if the process is killed. Keep the inode
    # in place so two processes can never acquire locks on different files.
    import fcntl
    out.mkdir(parents=True, exist_ok=True)
    with (out / '.eval.lock').open('a+') as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(f'an evaluation is already running in {out}') from None
        try:
            yield
        finally:
            fcntl.flock(file, fcntl.LOCK_UN)


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode() + b'\0')
            digest.update(path.read_bytes())
    return digest.hexdigest()


def prepare(out: Path, *, cfg, domain, settings, tasks, arms, skill_path, upstream_base_url, resume, learner_base_url=None):
    manifest_path = out / 'run_manifest.json'
    rows = read_rows(out / 'attempts.jsonl')
    task_map = {task.id: task for task in tasks}
    selected = {(task.id, arm) for task in tasks for arm in arms}
    if not resume and any((out / name).exists() for name in
                          ('attempts.jsonl', 'run_manifest.json', 'learner_ledger.jsonl', 'harbor-jobs')):
        raise ValueError(f'{out} already contains evaluation data; use --resume or a new --out')
    domain_settings = asdict(domain)
    for key in ('eval_budget_tokens', 'judge_budget_tokens'):
        domain_settings.pop(key)
    manifest = json.loads(json.dumps({
        'schema_version': 1, 'domain': domain_settings, 'learner': {k: v for k, v in asdict(settings).items() if k != 'legacy_context'},
        'upstream_base_url': upstream_base_url.rstrip('/'), 'arms': sorted(arms),
        'tasks': {task.id: {'name': task.name, 'sha256': tree_digest(task.dir)} for task in tasks},
        'skill_sha256': tree_digest(skill_path) if 'skill' in arms else None,
    }, default=str))
    if learner_base_url is not None:
        manifest["learner_base_url"] = learner_base_url
    from .openhands_context import context_policy
    policy = context_policy(settings.agent, settings.model, legacy=settings.legacy_context)
    if policy:
        manifest['context_policy'] = policy
    # The earlier DeepSeek adapter changed the tool protocol without changing
    # LearnerSettings. Never silently resume those results with the stock agent.
    if (settings.agent == 'openhands-sdk'
            and settings.model.removeprefix('openai/') == 'deepseek-ai/DeepSeek-R1-Distill-Qwen-32B'):
        manifest['agent_protocol'] = 'openhands-sdk-native-tools-v1'
    if resume and manifest_path.exists():
        if json.loads(manifest_path.read_text()) != manifest:
            raise ValueError('resume configuration differs: keep the same tasks, arms, model, grader, dataset, skill and agent protocol; use a new output directory after changing protocols')
    elif resume:
        # Older runs predate manifests. Only import the recoverable HealthBench
        # control-arm case; never silently infer the identity of an old skill.
        if domain.benchmark != 'healthbench' or 'skill' in arms or not rows:
            raise ValueError('legacy resume requires saved HealthBench baseline/placebo attempts')
        for row in rows:
            task = task_map.get(row.get('task_id'))
            if task is None:
                raise ValueError('saved task is not in the requested dataset')
            trial = Path(row.get('trial_dir') or '').resolve()
            if not trial.is_relative_to((out / 'harbor-jobs').resolve()):
                raise ValueError('saved trial is outside this run directory')
            agent = json.loads((trial / 'config.json').read_text())['agent']
            command, _ = harbor.build_command(task, task.dir, settings=settings,
                gateway_url='http://checkpoint', gateway_key='checkpoint', jobs_dir=out,
                job_name='checkpoint', staged_skill=None)
            if (agent.get('model_name') != command[command.index('-m') + 1]
                    or (agent.get('import_path') or agent.get('name')) != command[command.index('-a') + 1]
                    or agent.get('kwargs') != settings.agent_kwargs):
                raise ValueError('legacy resume learner differs from saved Harbor configuration')
            result = json.loads((trial / 'result.json').read_text())
            attempt = attempt_from_trial(task, trial, result)
            if attempt['status'] not in ('ok', 'invalid_output') or score(task, attempt) != row['score']:
                raise ValueError('legacy checkpoint differs from saved verifier result')
        graders = {row.get('model') for row in read_rows(out / 'grader_ledger.jsonl')}
        if graders != {settings.judge_model}:
            raise ValueError('legacy resume grader differs from the saved ledger')
    completed = {}
    for row in rows:
        key = (row.get('task_id'), row.get('arm'))
        if key not in selected or key in completed:
            raise ValueError('checkpoint has duplicate or unselected task/arm pairs')
        if row.get('status') == 'agent_timeout':
            if (domain.benchmark != 'qfbench' or row.get('score') != 0.0
                    or row.get('passed') is not False
                    or row.get('error_class') != 'harbor_exception:AgentTimeoutError'):
                raise ValueError('checkpoint contains an invalid agent timeout')
        if row.get('status') not in ('ok', 'invalid_output', 'agent_timeout') or 'score' not in row:
            raise ValueError('checkpoint contains an incomplete attempt')
        completed[key] = row
    # Validate both ledgers before writing anything to the checkpoint directory.
    for name in ('learner_ledger.jsonl', 'grader_ledger.jsonl'):
        read_rows(out / name)
    write_json(manifest_path, manifest)
    return rows, completed
