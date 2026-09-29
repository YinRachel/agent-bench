# Starting agent-bench on Viking

Project account: `cs-caa-2026`. All batch scripts include this account.
Here, finance means this repository's **QuantitativeFinance-Bench**, domain `qf`;
it is not the separate financial document QA benchmark called FinanceBench.

## Selected setup: Viking GPU models, local benchmark harness

Keep Docker and `stbench eval` on your current machine. Run the models from your
existing `local-vllm.toml` on Viking. The `serve.sbatch` script requests one H100
per model; two simultaneous jobs use the documented two-H100 per-user allowance.
These are starting resource settings, **not a cluster-tested deployment**.
The Qwen3-32B learner is unquantized; the auxiliary checkpoint is FP8.

First connect/copy as described below. Install `uv` on Viking if needed using
its official installation instructions, then create a separate inference
environment (do not install vLLM into the benchmark environment):

```bash
uv venv --python 3.12 ~/venvs/viking-vllm
uv pip install --python ~/venvs/viking-vllm/bin/python vllm
uv pip freeze --python ~/venvs/viking-vllm/bin/python > ~/venvs/viking-vllm-requirements.txt
```

This follows the current vLLM installation approach and records the resolved
versions. CUDA/driver compatibility still needs verification on Viking; if the
wheel cannot run against Viking's NVIDIA driver, use a compatible release or
an Apptainer environment agreed with support. Do not upgrade the system driver.
Model downloads use `~/scratch/huggingface`; allow space for both checkpoints.
First startup downloads weights, so it can take substantially longer. If compute
nodes cannot access Hugging Face, pre-download the same checkpoints through a
Viking-supported transfer route into that cache.

On Viking:

```bash
cd ~/agent-bench
mkdir -p ~/scratch/agent-bench-logs
sbatch --job-name=stbench-learner \
  --output="$HOME/scratch/agent-bench-logs/learner-%j.log" \
  scripts/viking/serve.sbatch learner
sbatch --job-name=stbench-auxiliary \
  --output="$HOME/scratch/agent-bench-logs/auxiliary-%j.log" \
  scripts/viking/serve.sbatch auxiliary
squeue -u "$USER" -o '%.18i %.20j %.8T %.20N'
```

The `auxiliary` server disables thinking by default with
`--default-chat-template-kwargs '{"enable_thinking": false}'`, so HealthBench
judge requests can use their output budget for grading verdicts. After syncing
the script to Viking, submit it directly with
`sbatch scripts/viking/serve.sbatch auxiliary`.

The auxiliary job also defaults `VLLM_USE_DEEP_GEMM=0` and
`VLLM_MOE_USE_DEEP_GEMM=0`. DeepGEMM's JIT needs a discoverable CUDA toolkit;
without one, FP8 startup can fail in `deep_jit::CUDA::find_cuda_toolkit`
with a `home_path` assertion even when the GPU driver works. These defaults
allow vLLM to select alternative FP8 kernels; performance can differ. To opt
back in after configuring a compatible toolkit on the compute node, export
both variables as `1` before submitting. A successful GPU startup still needs
to be verified on Viking.

For `qf` alone only the learner is needed. For `tau3`, launch both. Check each
log for successful server startup and its allocated node. On your **local
machine**, run these in two terminals, substituting those node names:

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -J YOUR_USERNAME@viking.york.ac.uk \
  -L 127.0.0.1:8001:127.0.0.1:18001 YOUR_USERNAME@LEARNER_NODE
```

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -J YOUR_USERNAME@viking.york.ac.uk \
  -L 127.0.0.1:8000:127.0.0.1:18000 YOUR_USERNAME@AUXILIARY_NODE
```

This assumes Viking permits SSH to your allocated compute nodes via the login
host; this has not been verified. If denied, ask support for the supported tunnel
method. Keep model servers bound to loopback. Existing local services/tunnels on
8000/8001 must be stopped or use different local ports and update a copied config.
The model servers stop when their allocation ends, so keep evaluations within
the remaining job time and cancel idle serving jobs with `scancel JOBID`.

Back in your local repository:

```bash
curl --fail http://127.0.0.1:8001/v1/models
curl --fail http://127.0.0.1:8000/v1/models
uv run python scripts/check_native_tools.py --config local-vllm.toml
uv run stbench eval --config local-vllm.toml --domain qf \
  --arms baseline --limit 1 --concurrency 1 --out runs/viking-qf-pilot
uv run stbench eval --config local-vllm.toml --domain tau3 \
  --arms baseline --limit 1 --concurrency 1 --out runs/viking-tau3-pilot
```

Skip the auxiliary curl for qf-only runs. Confirm both model IDs match the config.
Do not run a pilot if the tool probe fails. The tau3 pilot additionally validates
the simulated user and assertion judge; inspect exceptions and trajectories
before scaling. Use fresh output directories if these names already exist.
This is a research configuration using local models, not the fixed organizer
models. No Runware inference is requested by this configuration.

Parser choices follow [Qwen3's deployment instructions](https://github.com/QwenLM/Qwen3/blob/main/docs/source/deployment/vllm.md)
and [vLLM's Qwen3.5 recipe](https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen3.5.html).

## First check: container compatibility

The harness explicitly selects Harbor's Docker backend, builds task images and
uses Docker networking for its metering gateway. Viking documents
[Apptainer](https://vikingdocs.york.ac.uk/applications/apptainer.html).
An Apptainer image conversion does not implement the Docker API or Compose.
Docker availability and permission to use it on Viking are **not yet verified**.
Do not start a Docker daemon or assume rootless Docker is supported without
checking with Viking support. No benchmark jobs have been submitted by this setup.

Two possible arrangements:

- Run the Docker harness on your existing machine, with model inference on a
  Viking GPU allocation and SSH forwarding to the model endpoint. This avoids
  changing the benchmark sandbox backend.
- Run everything on Viking only after an approved Docker setup is confirmed,
  or after implementing and validating a different Harbor environment backend.

## Connect and copy the repository

Connect to the University network or VPN, then use your York IT username:

```bash
ssh YOUR_USERNAME@viking.york.ac.uk
mkdir -p ~/agent-bench ~/scratch/agent-bench-logs
exit
```

From your local repository directory, copy code without local environments,
credentials, downloaded data or run outputs:

```bash
rsync -av --exclude='.git/' --exclude='.venv/' --exclude='.env' \
  --exclude='.env.*' --exclude='dataset/' --exclude='runs/' \
  --exclude='__pycache__/' --exclude='reports/' \
  ./ YOUR_USERNAME@viking.york.ac.uk:~/agent-bench/
```

On Viking, submit the small runtime check:

```bash
cd ~/agent-bench
sbatch --output="$HOME/scratch/agent-bench-logs/preflight-%j.log" \
  scripts/viking/preflight.sbatch
squeue -u "$USER"
```

Inspect the resulting log in `~/scratch/agent-bench-logs/`. Failure when checking
Docker is a useful result: it establishes that the current harness cannot yet
run on that compute node. Share the log without credentials.

## Pilot evaluations, only with a working approved Docker runtime

Use Python **3.12 or newer** (the Python 3.11 example in Viking's quickstart is
too old for this repository). Make `uv` available on the batch job PATH, create
a fresh Viking environment with `uv sync --locked --python 3.12`, and download
the training dataset with `uv run stbench data pull`. Follow Viking's policy for
software installation and data transfers; do not run evaluations on login nodes.
Store the Runware key in a private `.env` file on Viking, following `.env_example`,
and `chmod 600 .env`. Do not put keys in scripts or job logs.

The following jobs use the existing `hackathon.toml` API models, so they need no
GPU. Each runs one baseline task at concurrency one and can spend API credits:

```bash
sbatch --output="$HOME/scratch/agent-bench-logs/qf-%j.log" \
  scripts/viking/eval.sbatch qf
sbatch --output="$HOME/scratch/agent-bench-logs/tau3-%j.log" \
  scripts/viking/eval.sbatch tau3
```

Outputs go to `~/scratch/agent-bench-runs/DOMAIN-JOBID`. Inspect `eval_result.json`,
`attempts.jsonl` and trial exceptions before scaling. Additional arguments are
passed to `stbench eval`, for example `--limit 5` or
`--arms baseline,skill --skill submissions/YOUR_TEAM/qf`. You can set
`STBENCH_CONFIG` to a research config. A config using localhost model endpoints
requires servers or tunnels on the **same host as the evaluator**; a tunnel on
your laptop or a login node is not automatically available on a compute node.

Monitor with `squeue -u "$USER"`, inspect completed jobs using
`sacct -j JOBID --format=JobID,State,Elapsed,MaxRSS,ExitCode`, and cancel with
`scancel JOBID`. For continuation, pass `--resume --out ORIGINAL_OUTPUT_DIRECTORY`
and the same task selection/configuration to the evaluation script.

## GPU resource notes

Viking documents A40 GPUs in `gpu` and H100 GPUs in `gpuplus`, requested with
`#SBATCH --gres=gpu:1`. Choose GPU count and memory after choosing the model,
precision and context size. The current research config has a Qwen3-32B learner
and a separate Qwen3.5-35B-A3B-FP8 auxiliary model; serving both is a separate
resource decision. Validate native tool calls with `scripts/check_native_tools.py`
before a benchmark pilot. The provided GPU serving script still needs runtime
validation on Viking; the CPU evaluation script does not launch models.

References: [login and job submission](https://vikingdocs.york.ac.uk/getting_started/quickstart.html),
[partitions](https://vikingdocs.york.ac.uk/using_viking/resource_partitions.html),
[storage](https://vikingdocs.york.ac.uk/getting_started/storage_on_viking.html).
Write job outputs to scratch and back up results: scratch is not backed up and
the documented policy removes data not touched for 90 days.
