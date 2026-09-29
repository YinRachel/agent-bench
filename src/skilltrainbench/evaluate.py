"""`stbench eval`: run the learner on tasks with and without a skill, then score.

Arms differ only by the mounted skill folder: `baseline` (none), `placebo` (a
generic content-free skill) and `skill`. All learner calls go through one
metering gateway; grader / simulated-user calls through a second one.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import replace
from pathlib import Path

import httpx

from . import checkpoint, harbor
from .config import HackathonCfg, learner_settings, task_names
from .gateway import (AttemptTagRegistry, BudgetMeter, Ledger, LocalGatewayServer, build_app,
                      fetch_prices, learner_request_options, tagged)
from .scoring import Pair, summarize
from .tasks import Task, is_pass, load_task, score

ARMS = ("baseline", "placebo", "skill")
_RETRY_DELAYS = (0.5, 2.0, 5.0)  # transient upstream/Docker failures often clear within seconds

_PLACEBO_SKILL = (
    "---\nname: placebo\ndescription: generic problem-solving guidance (control arm)\n---\n"
    "Read the problem carefully. Work through it step by step and show your reasoning. "
    "Double-check your arithmetic. End with a line: #### <answer>.\n"
)


def write_placebo(placebo_dir: Path) -> Path:
    placebo_dir.mkdir(parents=True, exist_ok=True)
    (placebo_dir / "SKILL.md").write_text(_PLACEBO_SKILL)
    return placebo_dir


async def _attempt_with_retries(task: Task, skill_dir: Path | None, sem: asyncio.Semaphore, *,
                                registry: AttemptTagRegistry | None, tags: dict, **run_kw) -> dict:
    """One scored attempt; retries infrastructure failures, never a wrong answer."""
    judged = task.benchmark == "healthbench"
    for n, delay in enumerate((0.0, *_RETRY_DELAYS)):
        if delay:
            await asyncio.sleep(delay)
        attempt_id = secrets.token_urlsafe(24) if judged else ""
        registration = registry.registered(attempt_id, **tags) if judged and registry else None
        if registration is not None:
            registration.__enter__()
        try:
            async with sem:
                attempt = await harbor.run_attempt(task, skill_dir, attempt_id=attempt_id, **run_kw)
        finally:
            if registration is not None:
                registration.__exit__(None, None, None)
        status = attempt.get("status")
        blocked = status == "budget_exhausted"
        ok_statuses = {"ok", "invalid_output"} if judged else {"ok"}
        error = None if status in ok_statuses or blocked else f"{task.benchmark}_runtime_{status}"
        if not error or blocked or n == len(_RETRY_DELAYS):
            return {**attempt, "blocked": blocked, "error": error}
    raise AssertionError("unreachable")


async def run_eval(cfg: HackathonCfg, domain_name: str, *, skill_dir: str | Path | None, out: str | Path,
                   arms: list[str], task_ids: list[str] | None = None, limit: int | None = None,
                   upstream_base_url: str, upstream_key: str | None, concurrency: int | None = None,
                   model: str | None = None, resume: bool = False,
                   learner_budget_tokens: int | None = None, grader_budget_tokens: int | None = None,
                   learner_base_url: str | None = None, learner_key: str | None = None,
                   legacy_context: bool = False) -> dict:
    with checkpoint.run_lock(Path(out)):
        return await _run_eval(cfg, domain_name, skill_dir=skill_dir, out=out, arms=arms,
            task_ids=task_ids, limit=limit, upstream_base_url=upstream_base_url, upstream_key=upstream_key,
            concurrency=concurrency, model=model, resume=resume,
            learner_budget_tokens=learner_budget_tokens, grader_budget_tokens=grader_budget_tokens,
            learner_base_url=learner_base_url, learner_key=learner_key, legacy_context=legacy_context)


async def _run_eval(cfg: HackathonCfg, domain_name: str, *, skill_dir: str | Path | None, out: str | Path,
                   arms: list[str], task_ids: list[str] | None = None, limit: int | None = None,
                   upstream_base_url: str, upstream_key: str | None, concurrency: int | None = None,
                   model: str | None = None, resume: bool = False,
                   learner_budget_tokens: int | None = None, grader_budget_tokens: int | None = None,
                   learner_base_url: str | None = None, learner_key: str | None = None,
                   legacy_context: bool = False) -> dict:
    domain = cfg.domain(domain_name)
    if learner_base_url is None:
        learner_base_url = cfg.learner_upstream_base_url
    if learner_base_url is not None:
        from urllib.parse import urlsplit
        parsed = urlsplit(learner_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("--learner-base-url must be an HTTP(S) URL without embedded credentials")
        learner_base_url = learner_base_url.rstrip("/").removesuffix("/v1")
    if not arms or len(set(arms)) != len(arms) or any(a not in ARMS for a in arms):
        raise ValueError(f"arms must be drawn from {ARMS}, got {arms}")
    if "skill" in arms and not skill_dir:
        raise ValueError("the skill arm needs --skill")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    settings = learner_settings(cfg, domain)
    if model is not None:
        settings = replace(settings, model=model)
    if legacy_context:
        from .openhands_context import context_policy
        if not resume or not context_policy(settings.agent, settings.model):
            raise ValueError("--legacy-context requires --resume with the Qwen3-32B OpenHands learner")
        settings = replace(settings, legacy_context=True)
    names = task_names(domain, task_ids=task_ids, limit=limit)
    tasks = [load_task(domain.benchmark, domain.dataset_dir, n) for n in names]
    skill_path = Path(skill_dir).resolve() if skill_dir else None
    rows, completed = checkpoint.prepare(out, cfg=cfg, domain=domain, settings=settings, tasks=tasks,
        arms=arms, skill_path=skill_path, upstream_base_url=upstream_base_url, resume=resume, learner_base_url=learner_base_url)
    learner_ledger = Ledger(out / "learner_ledger.jsonl")
    needs_aux = domain.benchmark != "qfbench"
    aux_ledger = Ledger(out / "grader_ledger.jsonl") if needs_aux else None
    remaining = len(tasks) * len(arms) - len(completed)
    learner_budget = domain.eval_budget_tokens if learner_budget_tokens is None else learner_budget_tokens
    grader_budget = domain.judge_budget_tokens if grader_budget_tokens is None else grader_budget_tokens
    if learner_budget <= 0 or (grader_budget is not None and grader_budget <= 0):
        raise ValueError("token budgets must be positive")
    print(f"{len(tasks)} tasks × {len(arms)} arms: reusing {len(completed)} attempts; {remaining} remaining", flush=True)
    if not remaining:
        return _write_result(out, domain, settings, skill_path, arms, names, tasks, completed, learner_ledger, aux_ledger, learner_base_url)
    checkpoint.append_row(out / "sessions.jsonl", {"learner_budget_tokens": learner_budget,
        "grader_budget_tokens": grader_budget, "reused_attempts": len(completed), "remaining_attempts": remaining})
    arm_dirs = {"baseline": None, "skill": skill_path}
    if "placebo" in arms:
        arm_dirs["placebo"] = write_placebo(out / "placebo_skill")

    headers = {"authorization": f"Bearer {upstream_key}"} if upstream_key else {}
    upstream = httpx.AsyncClient(base_url=upstream_base_url, headers=headers, timeout=600.0)
    prices = await fetch_prices(upstream) if learner_base_url is None or needs_aux else {}
    learner_upstream = upstream
    if learner_base_url is not None:
        # An explicit learner endpoint never inherits the grader/provider key.
        learner_headers = {"authorization": f"Bearer {learner_key}"} if learner_key else {}
        learner_upstream = httpx.AsyncClient(base_url=learner_base_url, headers=learner_headers,
                                            timeout=max(600.0, float(settings.agent_timeout_s or 0)))
    learner_prices = await fetch_prices(learner_upstream) if learner_base_url is not None else prices
    learner_meter = BudgetMeter(learner_budget)
    learner_gw = await LocalGatewayServer(build_app(learner_meter, client=learner_upstream, ledger=learner_ledger,
                                                    prices=learner_prices, learner_model=settings.model)).start()
    aux_meter = aux_registry = aux_key = aux_gw = aux_exhausted = None
    if needs_aux:
        aux_meter, aux_registry = BudgetMeter(grader_budget), AttemptTagRegistry()
        aux_key = secrets.token_urlsafe(32)
        aux_app = build_app(aux_meter, client=upstream, ledger=aux_ledger, virtual_key=aux_key,
                            attempt_registry=aux_registry, prices=prices)
        aux_gw = await LocalGatewayServer(aux_app).start()
        if domain.benchmark == "healthbench":
            aux_exhausted = lambda: bool(aux_app.state.budget_rejected)  # noqa: E731
        else:
            aux_exhausted = aux_meter.exhausted

    sem = asyncio.Semaphore(concurrency or cfg.concurrency)

    async def _arm(task: Task, arm: str) -> float | None:
        if (task.id, arm) in completed:
            return completed[(task.id, arm)]["score"]
        with tagged(phase="eval", arm=arm, task_id=task.id):
            attempt = await _attempt_with_retries(
                task, arm_dirs[arm], sem,
                registry=aux_registry, tags={"phase": "eval", "arm": arm, "task_id": task.id},
                settings=settings, gateway_url=learner_gw.container_url, gateway_key="stbench-no-secret",
                jobs_dir=out / "harbor-jobs",
                aux_url=aux_gw.container_url if aux_gw else None, aux_key=aux_key,
                aux_exhausted=None if task.benchmark == "healthbench" else aux_exhausted,
            )
        value = score(task, attempt)
        if aux_exhausted is not None and aux_exhausted():
            raise RuntimeError("grader/simulator budget pool exhausted; results would be false zeros")
        if attempt["blocked"]:
            raise RuntimeError("learner budget pool exhausted mid-evaluation (gateway 402): "
                               "results would be false failures — raise eval_budget_tokens")
        if attempt["error"]:
            detail = attempt.get("artifacts", {}).get("stderr_tail") or ""
            raise RuntimeError(f"attempt failed after retries ({attempt['error']}) for {task.name!r} arm {arm!r}: "
                               "an upstream/gateway/Docker problem, not a learner mistake"
                               f"\n  error_class: {attempt.get('error_class')}"
                               + (f"\n  harbor stderr (tail):\n{detail}" if detail else ""))
        row = {"task_id": task.id, "task_name": task.name, "arm": arm, "score": value,
                     "passed": None if value is None else is_pass(value), "answer": attempt.get("answer", ""),
                     "status": attempt.get("status"), "trial_dir": attempt.get("artifacts", {}).get("trial_dir")}
        checkpoint.append_row(out / "attempts.jsonl", row)
        rows.append(row)
        completed[(task.id, arm)] = row
        print(f"Completed {len(completed)}/{len(tasks) * len(arms)}: {task.name} [{arm}]", flush=True)
        return value

    pending = [asyncio.create_task(_arm(task, arm)) for task in tasks for arm in arms
               if (task.id, arm) not in completed]
    try:
        await asyncio.gather(*pending)
    finally:
        # Stop and reap every attempt before closing its gateways. Otherwise a
        # single failure leaves sibling attempts using already-closed servers.
        for future in pending:
            if not future.done():
                future.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await learner_gw.stop()
        if aux_gw is not None:
            await aux_gw.stop()
        if learner_base_url is not None:
            await learner_upstream.aclose()
        await upstream.aclose()

    return _write_result(out, domain, settings, skill_path, arms, names, tasks, completed, learner_ledger, aux_ledger, learner_base_url)


def _write_result(out, domain, settings, skill_path, arms, names, tasks, completed, learner_ledger, aux_ledger, learner_base_url):
    pairs = []
    for task in tasks:
        by_arm = {arm: completed[(task.id, arm)]["score"] for arm in arms}
        pairs.append(Pair(task_id=task.id, seed=0, baseline=by_arm.get("baseline"), placebo=by_arm.get("placebo"),
                          skill=by_arm.get("skill"), domain=task.benchmark,
                          invalidated=frozenset(arm for arm in arms if by_arm[arm] is None)))
    by_id = {t.id: t.name for t in tasks}
    summary = summarize(list(pairs))
    from .openhands_context import context_policy
    policy = context_policy(settings.agent, settings.model, legacy=settings.legacy_context)
    result = {
        "domain": domain.name,
        "benchmark": domain.benchmark,
        "learner": {"model": settings.model, "agent": settings.agent, "agent_kwargs": settings.agent_kwargs,
                    "request_options": learner_request_options(settings.model),
                    **({"context_policy": policy} if policy else {}),
                    **({"sdk_llm_options": {"api_mode": "chat", "reasoning_effort": "none",
                        **({"max_input_tokens": 16384, "max_output_tokens": 4096, "timeout": 1800}
                           if settings.model.removeprefix("openai/") == "qwen3-stbench:8b" else {})}}
                       if settings.agent == "openhands-sdk" and learner_request_options(settings.model) else {})},
        **({"learner_base_url": learner_base_url} if learner_base_url is not None else {}),
        "skill_dir": str(skill_path) if skill_path else None,
        "arms": arms,
        "tasks": names,
        "summary": summary,
        "per_task": [{**r, "task_name": by_id.get(r["task_id"], r["task_id"])} for r in summary["per_task"]],
        "learner_usage": learner_ledger.usage(),
        "learner_cost": learner_ledger.summary()["cost"],
        "grader_usage": aux_ledger.usage() if aux_ledger else None,
        "grader_cost": aux_ledger.summary()["cost"] if aux_ledger else None,
        "note": "local evaluation on training tasks; the leaderboard scores private held-out tasks",
    }
    checkpoint.write_json(out / "eval_result.json", result)
    return result


def format_result(result: dict) -> str:
    s = result["summary"]
    lines = [f"{result['domain']} ({result['benchmark']}) · learner {result['learner']['model']} "
             f"via {result['learner']['agent']} · {s.get('n_tasks')} tasks"]
    for key in ("baseline_rate", "placebo_rate", "skill_rate", "delta", "net_delta", "ci95", "note"):
        if s.get(key) is not None:
            lines.append(f"  {key:<14} {s[key]}")
    for who in ("learner", "grader"):
        usage = result.get(f"{who}_usage")
        if usage:
            usd = (result.get(f"{who}_cost") or {}).get("estimated_usd")
            cost = f" · ${usd:.4f}" if usd is not None else ""
            lines.append(f"  {who} tokens {usage['total_tokens']}{cost}")
    return "\n".join(lines)
