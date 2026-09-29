"""Context policy for the 32K Qwen3 server; no task or reasoning overrides."""
from harbor.agents.installed.openhands_sdk import OpenHandsSDK

POLICY = {
    "version": 1,
    "server_context_tokens": 32768,
    "max_input_tokens": 27000,
    "max_output_tokens": 4096,
    # Event counting does not include every tool/schema/template token.
    "condenser_max_tokens": 20000,
}


def context_policy(agent: str, model: str, *, legacy: bool = False) -> dict | None:
    if not legacy and agent == "openhands-sdk" and model.removeprefix("openai/") == "Qwen/Qwen3-32B":
        return dict(POLICY)
    return None


def configure_runner(source: str) -> str:
    llm_marker = '    llm = LLM(**llm_kwargs)'
    agent_marker = '    agent = Agent(**agent_kwargs)'
    if source.count(llm_marker) != 1 or source.count(agent_marker) != 1:
        raise RuntimeError('Harbor OpenHands runner changed: cannot safely configure context')
    source = source.replace(llm_marker,
        f'    llm_kwargs.update(max_input_tokens={POLICY["max_input_tokens"]}, '
        f'max_output_tokens={POLICY["max_output_tokens"]})\n' + llm_marker)
    return source.replace(agent_marker,
        '    from openhands.sdk.context.condenser import LLMSummarizingCondenser\n'
        '    agent_kwargs["condenser"] = LLMSummarizingCondenser(\n'
        f'        llm=llm, max_tokens={POLICY["condenser_max_tokens"]})\n' + agent_marker)


class ContextOpenHandsSDK(OpenHandsSDK):
    async def install(self, environment) -> None:
        await super().install(environment)
        runner = self.logs_dir / 'run_agent.py'
        runner.write_text(configure_runner(runner.read_text()))
        await environment.upload_file(source_path=runner, target_path='/installed-agent/run_agent.py')
