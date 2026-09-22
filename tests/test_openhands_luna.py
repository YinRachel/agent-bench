import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from harbor.agents.installed import openhands_sdk
from skilltrainbench.openhands_luna import LunaOpenHandsSDK, configure_runner


class LunaRunnerTests(unittest.IsolatedAsyncioTestCase):
    def test_real_harbor_runner_changes_only_llm_options(self):
        original = Path(openhands_sdk.__file__).with_name('openhands_sdk_runner.py').read_text()
        updated = configure_runner(original)
        ast.parse(updated)
        injection = '    llm_kwargs.update(api_mode="chat", reasoning_effort="none")\n'
        self.assertEqual(updated.count(injection), 1)
        self.assertEqual(updated.replace(injection, ''), original)
        # Execute the actual constructor section against a capturing LLM class.
        section = updated[updated.index('    llm_kwargs: dict'):updated.index('    # Configure tools')]
        import os
        import textwrap
        from typing import Any
        env = {'model': 'openai/openai-gpt-5-6-luna', 'api_key': 'test',
               'base_url': 'http://gateway/v1', 'litellm_extra_body': {}, 'os': os,
               'Any': Any, 'LLM': lambda **kwargs: kwargs}
        exec(textwrap.dedent(section), env)
        self.assertEqual(env['llm']['api_mode'], 'chat')
        self.assertEqual(env['llm']['reasoning_effort'], 'none')
        self.assertEqual(env['llm']['model'], 'openai/openai-gpt-5-6-luna')

    def test_unknown_runner_fails_explicitly(self):
        for source in ('different runner', '    llm = LLM(**llm_kwargs)\n' * 2):
            with self.assertRaisesRegex(RuntimeError, 'runner changed'):
                configure_runner(source)

    async def test_install_uploads_configured_per_trial_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = root / 'run_agent.py'
            async def base_install(instance, environment):
                runner.write_text('def main():\n    llm = LLM(**llm_kwargs)\n')
            agent = LunaOpenHandsSDK(logs_dir=root, model_name='openai/openai-gpt-5-6-luna', version='1.47.0')
            environment = AsyncMock()
            with patch.object(openhands_sdk.OpenHandsSDK, 'install', base_install):
                await agent.install(environment)
            environment.upload_file.assert_awaited_once_with(source_path=runner, target_path='/installed-agent/run_agent.py')
            self.assertIn('api_mode="chat"', runner.read_text())
