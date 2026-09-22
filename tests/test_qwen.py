import unittest
from pathlib import Path
from dataclasses import replace
from skilltrainbench import config,harbor
from skilltrainbench.gateway import learner_request_options
from skilltrainbench.openhands_qwen import QwenOpenHandsSDK
from skilltrainbench.openhands_luna import configure_runner
from skilltrainbench.tasks import Task


class QwenTests(unittest.TestCase):
    def test_local_configuration_preserves_grader_and_default(self):
        original=config.load_config()
        local=config.load_config(config.REPO_ROOT/'qwen-local.toml')
        self.assertEqual(original.learner_model,'zai-glm-5-3-flash')
        self.assertEqual(local.learner_model,'qwen3-stbench:8b')
        self.assertEqual(local.concurrency,1)
        self.assertEqual(local.upstream_base_url,original.upstream_base_url)
        self.assertEqual(local.upstream_key_env,original.upstream_key_env)
        self.assertEqual(local.learner_upstream_base_url,'http://127.0.0.1:11434')
        self.assertIsNone(local.learner_upstream_key_env)
        self.assertIsNone(original.learner_upstream_base_url)
        for name,domain in original.domains.items():
            other=local.domain(name)
            self.assertEqual(other.judge_model,domain.judge_model)
            self.assertEqual(other.judge_temperature,domain.judge_temperature)
            self.assertEqual(other.max_iterations,domain.max_iterations)
            self.assertEqual(other.dataset_dir,domain.dataset_dir)

    def test_qwen_routes_through_openai_chat_adapter(self):
        cfg=config.load_config(config.REPO_ROOT/'qwen-local.toml')
        task=Task('test','test','healthbench',Path('/tmp'),1800)
        for model in ('qwen3-stbench:8b','openai/qwen3-stbench:8b'):
            settings=replace(config.learner_settings(cfg,cfg.domain('health')),model=model)
            command,env=harbor.build_command(task,task.dir,settings=settings,gateway_url='http://gateway',gateway_key='test',jobs_dir=Path('/tmp'),job_name='test',staged_skill=None)
            self.assertEqual(command[command.index('-m')+1],'openai/qwen3-stbench:8b')
            self.assertEqual(command[command.index('-a')+1],'skilltrainbench.openhands_qwen:QwenOpenHandsSDK')
            self.assertEqual(learner_request_options(model),{'reasoning_effort':'none','token_limit_parameter':'max_tokens'})
        source=configure_runner('def main():\n    llm = LLM(**llm_kwargs)\n',QwenOpenHandsSDK.llm_options)
        scope={'LLM':lambda **kwargs:kwargs,'llm_kwargs':{}}
        exec(source.replace('    llm = LLM(**llm_kwargs)','    return LLM(**llm_kwargs)'),scope)
        self.assertEqual(scope['main'](),{'api_mode':'chat','reasoning_effort':'none','max_input_tokens':16384,'max_output_tokens':4096,'timeout':1800})
