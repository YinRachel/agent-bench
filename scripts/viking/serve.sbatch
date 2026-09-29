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
        # DeepGEMM JIT requires a discoverable CUDA toolkit, which the vLLM
        # wheel alone does not provide. Use alternative FP8 kernels by default.
        export VLLM_USE_DEEP_GEMM=${VLLM_USE_DEEP_GEMM:-0}
        export VLLM_MOE_USE_DEEP_GEMM=${VLLM_MOE_USE_DEEP_GEMM:-0}
        printf 'DeepGEMM: %s MoE DeepGEMM: %s\n' "$VLLM_USE_DEEP_GEMM" "$VLLM_MOE_USE_DEEP_GEMM"
        # Return judge verdicts without spending the output budget on thinking.
        extra=(--language-model-only --default-chat-template-kwargs '{"enable_thinking": false}')
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
    --tensor-parallel-size 1 --max-model-len 32768 --max-num-seqs 2 \
    --gpu-memory-utilization 0.90 \
    --enable-auto-tool-choice --tool-call-parser "$parser" \
    --reasoning-parser qwen3 "${extra[@]}"
