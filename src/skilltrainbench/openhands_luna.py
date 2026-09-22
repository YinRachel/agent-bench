"""Luna's chat-completion configuration for the pinned Harbor OpenHands runner.

Harbor's SDK adapter currently exposes neither api_mode nor an effective
reasoning_effort setting. Keep its runner/tools/skills intact and inject only
these LLM constructor options into the per-trial copy, never site-packages.
"""
from harbor.agents.installed.openhands_sdk import OpenHandsSDK


_LLM_CONSTRUCTION = '    llm = LLM(**llm_kwargs)'


def configure_runner(source: str, extra_options: dict | None = None) -> str:
    if source.count(_LLM_CONSTRUCTION) != 1:
        raise RuntimeError('Harbor OpenHands runner changed: cannot safely configure LLM options')
    return source.replace(
        _LLM_CONSTRUCTION,
        '    llm_kwargs.update(api_mode="chat", reasoning_effort="none")\n'
        + (f'    llm_kwargs.update({extra_options!r})\n' if extra_options else '')
        + _LLM_CONSTRUCTION,
    )


class LunaOpenHandsSDK(OpenHandsSDK):
    llm_options: dict | None = None

    async def install(self, environment) -> None:
        await super().install(environment)
        runner = self.logs_dir / 'run_agent.py'
        runner.write_text(configure_runner(runner.read_text(), self.llm_options))
        await environment.upload_file(source_path=runner, target_path='/installed-agent/run_agent.py')
