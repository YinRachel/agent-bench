"""OpenHands settings for the local 20K-context Qwen Ollama model."""
from .openhands_luna import LunaOpenHandsSDK


class QwenOpenHandsSDK(LunaOpenHandsSDK):
    # The shared adapter forces chat completions and disables thinking. Reserve
    # 4K output tokens inside the model's explicitly configured 20K context.
    llm_options = {"max_input_tokens": 16384, "max_output_tokens": 4096, "timeout": 1800}
