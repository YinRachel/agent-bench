#!/usr/bin/env bash
#SBATCH --job-name=stbench-model
#SBATCH --account=cs-caa-2026
#SBATCH --partition=gpuplus
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=3-00:00:00
#SBATCH --output=stbench-model-%j.log

set -euo pipefail
umask 077
: "${SLURM_JOB_ID:?Submit with sbatch}"
# Match the sampler setting recorded in both successful Viking runs.
export VLLM_USE_FLASHINFER_SAMPLER=0
role=${1:?Usage: sbatch scripts/viking/serve.sbatch learner|auxiliary}
case "$role" in
    learner)
        model=Qwen/Qwen3-32B
        port=18001
        parser=hermes
        extra=()
        ;;
    auxiliary)
        model=Qwen/Qwen3.5-35B-A3B-FP8
        port=18000
        parser=qwen3_coder
        # Restore FP8 backends observed in the successful H100 run.
        export VLLM_USE_DEEP_GEMM=0
        export VLLM_MOE_USE_DEEP_GEMM=0
        # Return judge verdicts without spending the output budget on thinking.
        extra=(--language-model-only --gdn-prefill-backend triton --default-chat-template-kwargs '{"enable_thinking": false}')
        ;;
    *) echo 'Role must be learner or auxiliary' >&2; exit 2 ;;
esac
vllm_bin=${VIKING_VLLM_BIN:-$HOME/venvs/viking-vllm/bin/vllm}
[[ -x "$vllm_bin" ]] || { echo "Missing vLLM environment: $vllm_bin" >&2; exit 1; }
export HF_HOME=${VIKING_HF_HOME:-$HOME/scratch/huggingface}
export XDG_CACHE_HOME=$HOME/scratch/stbench-cache/$SLURM_JOB_ID
mkdir -p "$HF_HOME" "$XDG_CACHE_HOME"
nvidia-smi
"$vllm_bin" --version
printf 'Role: %s Model: %s Node: %s Port: %s\n' "$role" "$model" "$(hostname)" "$port"
echo 'Wait for the vLLM server startup message before opening the SSH tunnel.'
# Loopback only; reach via SSH to this allocated compute node through Viking.
exec "$vllm_bin" serve "$model" \
    --host 127.0.0.1 --port "$port" \
    --tensor-parallel-size 1 --max-model-len 32768 --max-num-seqs 1 \
    --gpu-memory-utilization 0.95 \
    --enable-auto-tool-choice --tool-call-parser "$parser" \
    --reasoning-parser qwen3 "${extra[@]}"
