"""Keep Qwen's OpenHands conversation inside the tau3 MCP protocol.

Plain final messages end an SDK run but are not delivered to tau3's user.
Allow at most two protocol reminders; never synthesize runtime messages or
termination signals. Harbor's trial timeout and gateway token budget still apply.
"""
from .openhands_context import ContextOpenHandsSDK


PROTOCOL = (
    "OpenHands/tau3 transport: plain assistant text is not delivered to the "
    "simulated customer. Use tau3-runtime.send_message_to_user for every "
    "customer-facing reply, then continue from the returned user response. "
    "When the case is resolved, call end_conversation. Do not finish the "
    "OpenHands run or emit a plain ###STOP### while the runtime is active. "
    "If the runtime reports that the conversation has ended, finish normally."
)


def configure_runner(source: str) -> str:
    marker = '    conversation.send_message(args.instruction)\n    conversation.run()'
    if source.count(marker) != 1:
        raise RuntimeError('Harbor OpenHands runner changed: cannot safely configure tau3')
    replacement = f'''    conversation.send_message(args.instruction + "\\n\\n" + {PROTOCOL!r})
    for tau3_run in range(3):
        conversation.run()
        tau3_path = Path(os.environ.get(
            "TAU3_RUNTIME_STATE_PATH", "/logs/agent/tau3_runtime_state.json"))
        if not tau3_path.is_file():
            break
        tau3_state = json.loads(tau3_path.read_text())
        if tau3_state.get("termination_reason") is not None:
            break
        # A failed bootstrap needs infrastructure diagnosis, not more reminders.
        if not tau3_state.get("bootstrap_complete"):
            break
        if tau3_run == 2:
            print("tau3 conversation still open after two protocol reminders")
            break
        conversation.send_message(
            "The tau3 conversation is still open. Your plain final answer was "
            "not sent to the customer. Continue using send_message_to_user "
            "for your reply and end_conversation only when resolved. "
            "Do not call start_conversation again.")'''
    return source.replace(marker, replacement)


class Tau3ContextOpenHandsSDK(ContextOpenHandsSDK):
    async def install(self, environment) -> None:
        await super().install(environment)
        runner = self.logs_dir / 'run_agent.py'
        runner.write_text(configure_runner(runner.read_text()))
        await environment.upload_file(source_path=runner, target_path='/installed-agent/run_agent.py')
