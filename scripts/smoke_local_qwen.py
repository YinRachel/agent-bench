"""Opt-in local-only OpenHands smoke test: uv run python scripts/smoke_local_qwen.py.

Requires Docker and the qwen3-stbench:8b Ollama alias. Calls no paid model/grader.
"""
import asyncio
import json
import tempfile
from pathlib import Path

import httpx

from skilltrainbench import harbor
from skilltrainbench.config import REPO_ROOT, load_config, learner_settings
from skilltrainbench.gateway import BudgetMeter, Ledger, LocalGatewayServer, build_app
from skilltrainbench.tasks import Task


async def main():
    cfg = load_config(REPO_ROOT / 'qwen-local.toml')
    settings = learner_settings(cfg, cfg.domain('health'))
    out = REPO_ROOT / 'runs' / 'qwen-openhands-smoke'
    out.mkdir(parents=True, exist_ok=True)
    meter, ledger = BudgetMeter(80000), Ledger()
    async with httpx.AsyncClient(base_url='http://127.0.0.1:11434', timeout=1800) as upstream:
        app = build_app(meter, client=upstream, ledger=ledger, learner_model=settings.model)
        server = await LocalGatewayServer(app).start()
        try:
            with tempfile.TemporaryDirectory(prefix='qwen-smoke-') as tmp:
                root = Path(tmp)
                (root / 'environment').mkdir()
                (root / 'tests').mkdir()
                (root / 'environment/Dockerfile').write_text(
                    'FROM python:3.12-slim@sha256:2fe5997d249a808b8eeea52c58a1dbffbba28754dc11699ef5c029f2d818ce79\nWORKDIR /app\n')
                (root / 'instruction.md').write_text(
                    'Use the terminal tool to write exactly QWEN_OPENHANDS_OK followed by a newline '
                    'to /app/qwen-proof.txt. Read it back using the terminal to verify it, then finish. '
                    'Do not inspect /tests or /logs. This is an integration smoke test.\n')
                (root / 'task.toml').write_text(
                    'schema_version = "1.4"\n[agent]\ntimeout_sec = 1800\n[verifier]\ntimeout_sec = 30\n'
                    '[environment]\nbuild_timeout_sec = 180\ncpus = 1\nmemory_mb = 1024\n')
                (root / 'tests/test.sh').write_text(
                    '#!/bin/bash\nmkdir -p /logs/verifier\n'
                    'if [ "$(cat /app/qwen-proof.txt 2>/dev/null)" = "QWEN_OPENHANDS_OK" ]; then '
                    'echo 1 > /logs/verifier/reward.txt; else echo 0 > /logs/verifier/reward.txt; fi\n')
                job_name = root.name
                cmd, env = harbor.build_command(Task('qwen-smoke', 'qwen-smoke', 'healthbench', root, 1800),
                    root, settings=settings, gateway_url=server.container_url, gateway_key='local-test',
                    jobs_dir=out, job_name=job_name, staged_skill=None)
                print(f'Starting OpenHands SDK {settings.agent_kwargs["version"]} with local Qwen; logs: {out/job_name}', flush=True)
                result = await harbor._run_harbor(cmd, 2100, harbor._child_env(env))
                print(json.dumps(result), flush=True)
                found = harbor._find_trial(out / job_name)
                if not found:
                    raise RuntimeError('No Harbor trial result; inspect the smoke-test logs')
                trial, data = found
                reward = (trial / 'verifier/reward.txt').read_text().strip()
                if data.get('exception_info') or reward != '1':
                    raise RuntimeError(f'Qwen tool test failed; inspect {trial}')
                print('PASS: local Qwen executed the terminal tool and wrote the expected file.', flush=True)
        finally:
            await server.stop()
            (out / 'learner_ledger.jsonl').write_text(ledger.to_jsonl())
            (out / 'usage.json').write_text(json.dumps(meter.usage(), indent=2))


if __name__ == '__main__':
    asyncio.run(main())
