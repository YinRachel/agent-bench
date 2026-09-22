"""Offline CLI-to-Harbor regression tests; no Docker or inference requests."""
import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from skilltrainbench import cli, config, evaluate, harbor
from skilltrainbench.tasks import Task


class ModelOverrideTests(unittest.TestCase):
    def run_cli(self, model=None, domain_name="health", configured_model=None):
        cfg = config.load_config()
        if configured_model is not None:
            cfg = replace(cfg, learner_model=configured_model)
        domain = cfg.domain(domain_name)
        original = asdict(cfg)
        expected = config.learner_settings(cfg, domain)
        effective = cfg.learner_model if model is None else model
        seen = []

        async def attempt(task, skill_dir, **kwargs):
            settings = kwargs["settings"]
            self.assertEqual(settings, replace(expected, model=effective))
            self.assertEqual(
                harbor._grader_env(task, settings, "http://aux", "test", "attempt"),
                harbor._grader_env(task, expected, "http://aux", "test", "attempt"),
            )
            command, env = harbor.build_command(
                task, task.dir, settings=settings, gateway_url=kwargs["gateway_url"],
                gateway_key="test", jobs_dir=kwargs["jobs_dir"], job_name="test",
                staged_skill=skill_dir,
            )
            formatted = effective if "/" in effective else f"openai/{effective}"
            self.assertEqual(command[command.index("-m") + 1], formatted)
            expected_agent = ("skilltrainbench.openhands_luna:LunaOpenHandsSDK"
                              if effective.removeprefix("openai/") == "openai-gpt-5-6-luna" else cfg.harbor_agent)
            self.assertEqual(command[command.index("-a") + 1], expected_agent)
            self.assertEqual(env["LLM_BASE_URL"], "http://gateway/v1")
            seen.append((skill_dir, settings))
            return {"status": "ok", "answer": "test"}

        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            root = Path(tmp)
            skill = root / "skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text("---\nname: test\ndescription: test\n---\nTest")
            task = Task("test", "test", domain.benchmark, root / "task", 30)
            stack.enter_context(patch("dotenv.load_dotenv"))
            stack.enter_context(patch.dict("os.environ", {"STBENCH_UPSTREAM_KEY": "test"}))
            stack.enter_context(patch.object(config, "load_config", return_value=cfg))
            stack.enter_context(patch.object(harbor, "egress_allowlist_supported", return_value=True))
            stack.enter_context(patch.object(evaluate, "task_names", return_value=[task.name]))
            stack.enter_context(patch.object(evaluate, "load_task", return_value=task))
            stack.enter_context(patch.object(evaluate, "score", return_value=1.0))
            stack.enter_context(patch.object(evaluate, "fetch_prices", new_callable=AsyncMock, return_value={}))
            gateway_builder = stack.enter_context(patch.object(evaluate, "build_app", wraps=evaluate.build_app))
            stack.enter_context(patch.object(evaluate.httpx, "AsyncClient"))
            # AsyncClient is never used for requests; only closed by run_eval.
            evaluate.httpx.AsyncClient.return_value.aclose = AsyncMock()
            server = stack.enter_context(patch.object(evaluate, "LocalGatewayServer"))
            server.return_value.start = AsyncMock(return_value=server.return_value)
            server.return_value.stop = AsyncMock()
            server.return_value.container_url = "http://gateway"
            stack.enter_context(patch.object(harbor, "run_attempt", side_effect=attempt))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            argv = ["eval", "--domain", domain_name, "--skill", str(skill),
                    "--arms", "baseline,placebo,skill", "--limit", "1", "--out", str(root / "out")]
            if model is not None:
                argv.extend(["--model", model])
            self.assertEqual(cli.main(argv), 0)
            result = json.loads((root / "out/eval_result.json").read_text())
            self.assertEqual(result["learner"]["model"], effective)
            self.assertEqual(gateway_builder.call_args_list[0].kwargs["learner_model"], effective)
            for auxiliary_call in gateway_builder.call_args_list[1:]:
                self.assertNotIn("learner_model", auxiliary_call.kwargs)
            expected_options = ({"reasoning_effort": "none", "token_limit_parameter": "max_completion_tokens"}
                                if effective.removeprefix("openai/") == "openai-gpt-5-6-luna" else {})
            self.assertEqual(result["learner"]["request_options"], expected_options)
            if expected_options:
                self.assertEqual(result["learner"]["sdk_llm_options"],
                                 {"api_mode": "chat", "reasoning_effort": "none"})
            else:
                self.assertNotIn("sdk_llm_options", result["learner"])
            self.assertEqual(len(seen), 3)
            self.assertEqual({p for p, _ in seen}, {None, skill, root / "out/placebo_skill"})
            self.assertTrue(all(settings is seen[0][1] for _, settings in seen))
        self.assertEqual(asdict(cfg), original)
        return effective

    def test_default_glm(self):
        self.assertEqual(self.run_cli(), "zai-glm-5-3-flash")

    def test_default_comes_from_config(self):
        self.run_cli(configured_model="CONFIG_MODEL")

    def test_override_all_arms_and_grader_isolation(self):
        for domain in ("health", "hle", "tau3", "qf"):
            with self.subTest(domain=domain):
                self.run_cli("MODEL_X", domain)

    def test_explicit_glm(self):
        self.run_cli("zai-glm-5-3-flash")

    def test_luna_all_arms_and_domains(self):
        for domain in ("health", "hle", "tau3", "qf"):
            with self.subTest(domain=domain):
                self.run_cli("openai-gpt-5-6-luna", domain)

    def test_luna_from_config(self):
        self.run_cli(configured_model="openai-gpt-5-6-luna")

    def test_luna_with_routing_prefix(self):
        self.run_cli("openai/openai-gpt-5-6-luna")

    def test_existing_provider_prefix_preserved(self):
        self.run_cli("openai/MODEL_X")

    def test_help(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as exited:
                cli.main(["eval", "--help"])
        self.assertEqual(exited.exception.code, 0)
        self.assertIn("--model MODEL", output.getvalue())
        self.assertIn("graders unchanged", output.getvalue())


if __name__ == "__main__":
    unittest.main()
