"""Offline interrupted/resumed evaluation tests: never contact Docker or a provider."""
import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from skilltrainbench import checkpoint, config, evaluate, harbor
from skilltrainbench.gateway import Ledger
from skilltrainbench.tasks import Task


class ResumeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / 'out'
        self.cfg = config.load_config()
        self.tasks = [Task('id-' + name, name, 'healthbench', self.root / name, 30) for name in ('one', 'two')]
        for task in self.tasks:
            task.dir.mkdir()
            (task.dir / 'instruction.md').write_text(task.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.object(evaluate, 'task_names', return_value=['one', 'two']))
        self.stack.enter_context(patch.object(evaluate, 'load_task', side_effect=lambda benchmark, root, name: next(t for t in self.tasks if t.name == name)))
        self.stack.enter_context(patch.object(evaluate, 'score', side_effect=lambda task, attempt: attempt.get('score', 0.5)))
        self.prices = self.stack.enter_context(patch.object(evaluate, 'fetch_prices', new_callable=AsyncMock, return_value={}))
        self.client = self.stack.enter_context(patch.object(evaluate.httpx, 'AsyncClient'))
        self.client.return_value.aclose = AsyncMock()
        server = self.stack.enter_context(patch.object(evaluate, 'LocalGatewayServer'))
        server.return_value.start = AsyncMock(return_value=server.return_value)
        server.return_value.stop = AsyncMock()
        server.return_value.container_url = 'http://gateway'
        self.builder = self.stack.enter_context(patch.object(evaluate, 'build_app', wraps=evaluate.build_app))
        self.attempt = self.stack.enter_context(patch.object(harbor, 'run_attempt', new_callable=AsyncMock))
        self.attempt.return_value = {'status': 'ok', 'score': 0.5}

    async def run_eval(self, **overrides):
        args = dict(skill_dir=None, out=self.out, arms=['baseline', 'placebo'],
                    upstream_base_url=self.cfg.upstream_base_url, upstream_key='test',
                    model='openai-gpt-5-6-luna', concurrency=1)
        args.update(overrides)
        return await evaluate.run_eval(self.cfg, 'health', **args)

    async def interrupt(self):
        calls = 0
        async def fail(task, skill_dir, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {'status': 'ok', 'score': 0.25}
            return {'status': 'budget_exhausted'}
        self.attempt.side_effect = fail
        with self.assertRaisesRegex(RuntimeError, 'budget pool exhausted'):
            await self.run_eval()
        self.attempt.side_effect = None

    async def test_resume_only_missing_pairs_and_merge_summary(self):
        await self.interrupt()
        before = (self.out / 'attempts.jsonl').read_bytes()
        self.assertEqual(len(checkpoint.read_rows(self.out / 'attempts.jsonl')), 1)
        self.attempt.reset_mock()
        result = await self.run_eval(resume=True, learner_budget_tokens=123456, grader_budget_tokens=654321)
        self.assertEqual(self.attempt.await_count, 3)
        self.assertTrue((self.out / 'attempts.jsonl').read_bytes().startswith(before))
        rows = checkpoint.read_rows(self.out / 'attempts.jsonl')
        self.assertEqual(len({(r['task_id'],r['arm']) for r in rows}), 4)
        self.assertEqual(result['summary']['n_tasks'], 2)
        self.assertEqual(result['summary']['baseline_rate'], 0.375)
        self.assertEqual(result['summary']['placebo_rate'], 0.5)
        self.assertEqual(self.builder.call_args_list[-2].args[0].total_tokens, 123456)
        self.assertEqual(self.builder.call_args_list[-1].args[0].total_tokens, 654321)

    async def test_completed_resume_does_not_start_gateways(self):
        await self.run_eval()
        self.attempt.reset_mock(); self.prices.reset_mock()
        result = await self.run_eval(resume=True)
        self.attempt.assert_not_awaited(); self.prices.assert_not_awaited()
        self.assertEqual(result['summary']['n_tasks'], 2)

    async def test_deepseek_native_protocol_rejects_old_manifest(self):
        model = 'deepseek-ai/DeepSeek-R1-Distill-Qwen-32B'
        await self.run_eval(model=model)
        path = self.out / 'run_manifest.json'
        manifest = json.loads(path.read_text())
        self.assertEqual(manifest.pop('agent_protocol'), 'openhands-sdk-native-tools-v1')
        path.write_text(json.dumps(manifest))
        self.attempt.reset_mock()
        with self.assertRaisesRegex(ValueError, 'agent protocol'):
            await self.run_eval(model=model, resume=True)
        self.attempt.assert_not_awaited()

    async def test_local_learner_isolated_from_grader_endpoint_and_credentials(self):
        self.cfg = replace(self.cfg, learner_upstream_base_url='http://configured:11434')
        grader_client, learner_client = MagicMock(), MagicMock()
        for client in (grader_client, learner_client):
            client.aclose = AsyncMock()
        self.client.side_effect = [grader_client, learner_client]
        result = await self.run_eval(model='qwen3-stbench:8b', learner_base_url='http://127.0.0.1:11434/v1/')
        calls = self.client.call_args_list
        self.assertEqual(calls[0].kwargs['base_url'], self.cfg.upstream_base_url)
        self.assertEqual(calls[0].kwargs['headers'], {'authorization':'Bearer test'})
        self.assertEqual(calls[1].kwargs['base_url'], 'http://127.0.0.1:11434')
        self.assertEqual(calls[1].kwargs['headers'], {})
        self.assertIs(self.builder.call_args_list[0].kwargs['client'], learner_client)
        self.assertIs(self.builder.call_args_list[1].kwargs['client'], grader_client)
        grader_client.aclose.assert_awaited_once()
        learner_client.aclose.assert_awaited_once()
        self.assertEqual(result['learner_base_url'], 'http://127.0.0.1:11434')
        self.assertEqual(result['learner']['sdk_llm_options']['max_input_tokens'], 16384)
        self.assertEqual(self.attempt.call_args.kwargs['settings'].judge_model, 'anthropic-claude-haiku-4-5')
        with self.assertRaisesRegex(ValueError, 'configuration differs'):
            await self.run_eval(resume=True, model='qwen3-stbench:8b', learner_base_url='http://different:11434')

    async def test_separate_learner_key_is_explicit(self):
        await self.run_eval(learner_base_url='http://local:8000', learner_key='local-key')
        self.assertEqual(self.client.call_args_list[1].kwargs['headers'], {'authorization':'Bearer local-key'})

    async def test_learner_endpoint_from_config(self):
        self.cfg = replace(self.cfg, learner_upstream_base_url='http://127.0.0.1:11434')
        result = await self.run_eval(model='qwen3-stbench:8b')
        self.assertEqual(self.client.call_args_list[1].kwargs['base_url'], 'http://127.0.0.1:11434')
        self.assertEqual(result['learner_base_url'], 'http://127.0.0.1:11434')

    async def test_existing_directory_requires_resume(self):
        await self.run_eval()
        before = (self.out / 'attempts.jsonl').read_bytes()
        with self.assertRaisesRegex(ValueError, 'already contains'):
            await self.run_eval()
        self.assertEqual((self.out / 'attempts.jsonl').read_bytes(), before)

    async def test_model_grader_dataset_or_arms_mismatch_rejected(self):
        await self.run_eval()
        for changes in ({'model':'zai-glm-5-3-flash'}, {'arms':['baseline']}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'configuration differs'):
                await self.run_eval(resume=True, **changes)
        domain = self.cfg.domain('health')
        self.cfg = replace(self.cfg, domains={**self.cfg.domains, 'health':replace(domain, judge_model='changed')})
        with self.assertRaisesRegex(ValueError, 'configuration differs'):
            await self.run_eval(resume=True)
        self.cfg = config.load_config()
        (self.tasks[0].dir / 'instruction.md').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'configuration differs'):
            await self.run_eval(resume=True)

    async def test_duplicate_or_corrupt_attempts_fail_without_rewriting(self):
        await self.run_eval()
        path = self.out / 'attempts.jsonl'
        original = path.read_text()
        for suffix in (original.splitlines()[0] + '\n', '{broken\n'):
            path.write_text(original + suffix)
            with self.assertRaises(ValueError):
                await self.run_eval(resume=True)
            self.assertEqual(path.read_text(), original + suffix)

    async def test_cumulative_ledger_cost_and_usage(self):
        await self.interrupt()
        ledger = Ledger(self.out / 'learner_ledger.jsonl')
        ledger.record({'status':'ok', 'prompt_tokens':10, 'completion_tokens':2, 'charged_tokens':12,
                       'cached_tokens':3, 'cost_usd':0.1, 'model':'openai-gpt-5-6-luna'})
        prior = (self.out / 'learner_ledger.jsonl').read_bytes()
        result = await self.run_eval(resume=True)
        self.assertEqual(result['learner_usage']['total_tokens'],12)
        self.assertEqual(result['learner_cost']['estimated_usd'],0.1)
        self.assertEqual((self.out / 'learner_ledger.jsonl').read_bytes(),prior)

    async def test_legacy_checkpoint_verified_and_imported(self):
        self.out.mkdir()
        trial = self.out / 'harbor-jobs/job/trial'
        (trial / 'verifier').mkdir(parents=True)
        (trial / 'verifier/grading_status').write_text('ok')
        settings = config.learner_settings(self.cfg, self.cfg.domain('health'))
        (trial / 'config.json').write_text(json.dumps({'agent': {
            'name': 'skilltrainbench.openhands_luna:LunaOpenHandsSDK',
            'model_name': 'openai/openai-gpt-5-6-luna', 'kwargs': settings.agent_kwargs}}))
        (trial / 'result.json').write_text(json.dumps({'verifier_result': {'rewards': {'reward': 0.25}},
                                                       'exception_info': None}))
        checkpoint.append_row(self.out / 'attempts.jsonl', {
            'task_id': self.tasks[0].id, 'task_name': 'one', 'arm': 'baseline',
            'status': 'ok', 'score': 0.25, 'trial_dir': str(trial)})
        Ledger(self.out / 'grader_ledger.jsonl').record({'model': settings.judge_model})
        result = await self.run_eval(resume=True)
        self.assertEqual(self.attempt.await_count, 3)
        self.assertEqual(result['summary']['baseline_rate'], 0.375)
        self.assertTrue((self.out / 'run_manifest.json').exists())

    async def test_legacy_model_mismatch_rejected(self):
        self.out.mkdir()
        trial = self.out / 'harbor-jobs/job/trial'
        trial.mkdir(parents=True)
        (trial / 'config.json').write_text(json.dumps({'agent': {'model_name': 'wrong'}}))
        checkpoint.append_row(self.out / 'attempts.jsonl', {
            'task_id': self.tasks[0].id, 'arm': 'baseline', 'status': 'ok', 'score': 0.25,
            'trial_dir': str(trial)})
        with self.assertRaisesRegex(ValueError, 'learner differs'):
            await self.run_eval(resume=True)
        self.attempt.assert_not_awaited()
        self.assertFalse((self.out / 'run_manifest.json').exists())

    def test_lock_prevents_concurrent_writers(self):
        with checkpoint.run_lock(self.out):
            with self.assertRaisesRegex(ValueError,'already running'):
                with checkpoint.run_lock(self.out):
                    self.fail('second lock acquired')
        with checkpoint.run_lock(self.out):
            pass

    async def test_cancellation_checkpoints_completed_and_reaps_siblings(self):
        started = asyncio.Event()
        cancelled = asyncio.Event()
        calls = 0
        async def block(task, skill_dir, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {'status':'ok','score':0.5}
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        self.attempt.side_effect = block
        running = asyncio.create_task(self.run_eval())
        await started.wait()
        running.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await running
        self.assertTrue(cancelled.is_set())
        self.assertEqual(len(checkpoint.read_rows(self.out/'attempts.jsonl')),1)


class PersistentLedgerTests(unittest.TestCase):
    def test_restart_appends_preserving_cost_usage_and_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'ledger.jsonl'
            ledger=Ledger(path)
            ledger.record({'status':'ok','model':'test','cost_usd':0.5,'prompt_tokens':10,'completion_tokens':5,'charged_tokens':15})
            restarted=Ledger(path)
            restarted.record({'status':'fail_closed','model':'test','prompt_tokens':0,'completion_tokens':0,'charged_tokens':20})
            self.assertEqual([r['seq'] for r in checkpoint.read_rows(path)],[0,1])
            self.assertEqual(restarted.usage()['total_tokens'],35)
            self.assertEqual(restarted.usage()['completion_tokens'],25)
            self.assertEqual(restarted.summary()['cost']['estimated_usd'],0.5)
            self.assertTrue(restarted.summary()['cost']['incomplete'])
