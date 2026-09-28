#!/usr/bin/env bash
#SBATCH --job-name=stbench-eval
#SBATCH --account=cs-caa-2026
#SBATCH --partition=nodes
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=04:00:00
#SBATCH --output=stbench-eval-%j.log

# Conditional template: requires a Viking-approved, working Docker runtime.
# Submit from the repository root. Default: one baseline task using Runware.
set -euo pipefail
umask 077
: "${SLURM_JOB_ID:?Submit this script with sbatch}"
domain=${1:?Usage: sbatch scripts/viking/eval.sbatch qf|tau3 [extra stbench eval flags]}
shift
case "$domain" in qf|tau3) ;; *) echo 'Domain must be qf or tau3' >&2; exit 2 ;; esac
cd "${STBENCH_REPO:-${SLURM_SUBMIT_DIR:?}}"
[[ -f pyproject.toml ]] || { echo 'Submit from the agent-bench repository root.' >&2; exit 2; }
command -v uv >/dev/null || { echo 'Install uv and run uv sync --locked first.' >&2; exit 1; }
command -v docker >/dev/null || { echo 'Docker unavailable; see docs/viking.md.' >&2; exit 1; }
docker info >/dev/null
docker compose version
run_root=${STBENCH_RUN_ROOT:-$HOME/scratch/agent-bench-runs}
mkdir -p "$run_root"
exec uv run --frozen stbench eval \
    --config "${STBENCH_CONFIG:-hackathon.toml}" \
    --domain "$domain" --arms baseline --limit 1 --concurrency 1 \
    --out "$run_root/$domain-$SLURM_JOB_ID" "$@"
