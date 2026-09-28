#!/usr/bin/env bash
#SBATCH --job-name=stbench-preflight
#SBATCH --account=cs-caa-2026
#SBATCH --partition=test
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:10:00
#SBATCH --output=stbench-preflight-%j.log

set -euo pipefail
printf 'Node: %s\n' "$(hostname)"
printf 'Job: %s\n' "${SLURM_JOB_ID:?Submit this script with sbatch}"
printf '\nAvailable commands (absence is diagnostic):\n'
for program in uv python3 docker apptainer; do
    command -v "$program" || true
done
if type module >/dev/null 2>&1; then
    module spider Apptainer 2>&1 || true
    module spider Python 2>&1 || true
fi
printf '\nDocker compatibility:\n'
if ! command -v docker >/dev/null 2>&1; then
    echo 'BLOCKED: this harness requires Docker; Apptainer is not a drop-in replacement.'
    exit 1
fi
docker version --format 'Client: {{.Client.Version}} Server: {{.Server.Version}}'
docker compose version
echo 'Docker daemon and Compose reachable. Image builds, networking and task execution still need a one-task pilot.'
