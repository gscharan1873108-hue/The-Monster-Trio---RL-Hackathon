# Patchwork: a hardened RL environment for code repair

An agent gets a small Python project with a bug or a missing feature, a README that specifies the
behaviour, and a few visible tests. It works through tools (read, edit, run Python, run tests) and is scored
by **hidden, programmatic checks** that run in a sandbox it cannot reach. Nothing is LLM-judged.

**Demo task (Run A): `slugify`** (easy, finishable by GPT-Luna in a handful of steps).

## Install Docker

**Windows (Docker Desktop + WSL 2).** Steps 1 and 3 need an Administrator PowerShell.

1. Enable WSL 2, then restart when prompted:
   ```powershell
   wsl --install
   ```
2. Make sure virtualization is on (Task Manager > Performance > CPU > "Virtualization: Enabled"); otherwise
   enable Intel VT-x / AMD-V in the BIOS.
3. Install Docker Desktop (tick "Use WSL 2" if you use the installer from https://www.docker.com/products/docker-desktop/):
   ```powershell
   winget install -e --id Docker.DockerDesktop
   ```
4. Start Docker Desktop, wait for "Engine running", then check in a new terminal:
   ```powershell
   docker --version
   docker compose version
   ```

Docker Desktop's licence may need approval on a company-managed laptop. Alternative: install Ubuntu with
`wsl --install -d Ubuntu`, install Docker Engine inside it, and run the repo from the WSL filesystem
(for example `~/rl-env`), not from a OneDrive path.

**Linux.** Install Docker Engine and the Compose v2 plugin from https://docs.docker.com/engine/install/, then
`sudo usermod -aG docker $USER` and log in again.

**macOS.** Install Docker Desktop from https://www.docker.com/products/docker-desktop/.

## Run it

```bash
cp .env.example .env            # fill MODEL, API_KEY, BASE_URL (MODEL=mock/solver runs offline)
                                # on Windows PowerShell: copy .env.example .env
docker compose up --build --abort-on-container-exit --exit-code-from harness
```

One command builds both images, starts the sandbox, runs the **oracle** (reference solution, must score
>= 0.95), then the **no-op** agent (must score <= 0.05) on the chosen task, and only then calls the model.
Settings come from `.env`: `MODEL`, `API_KEY`, `BASE_URL`, `TASK_ID`, optional `SEED`, `MODE`
(`full`, `all`, `baselines`), optional `APPEND_FILE` (default `inputs/append.txt`, added to the system
prompt exactly as written and logged; a named file that is missing or empty stops the run) and `MAX_TOKENS`.

```bash
MODE=baselines docker compose up --build --abort-on-container-exit --exit-code-from harness   # all tasks, no model
MODE=all       docker compose up --build --abort-on-container-exit --exit-code-from harness   # model on every task
TASK_ID=semver SEED=3 docker compose up --build --abort-on-container-exit --exit-code-from harness
```

Exit codes: 0 finished, 1 crash, 2 a baseline check failed, 3 bad configuration.
Logs go to `logs/<run-id>/`: `gate.jsonl`, `gate.json` (baseline results), `episode.jsonl` (one line per
model reply), `summary.json`, `append.txt`. A readable line per step is printed to the terminal.

## Tasks (9, three difficulty levels, every one seeded)

| id | level | what the agent must do |
|----|-------|------------------------|
| `slugify` (demo) | easy | accents, separator runs, word-boundary truncation, validation |
| `pricing` | easy | tier boundaries, half-up cent rounding, free-shipping rule, validation |
| `intervals` | easy | merge intervals: sorting, touching rule, no input mutation, coverage |
| `ttl_cache` | medium | TTL + LRU cache: expiry boundary, recency, purge-before-evict, stats |
| `csv_report` | medium | two modules: quoted-field CSV parser and exact-decimal group statistics |
| `ledger` | medium | atomic stock reservations, order lifecycle, defensive copies |
| `semver` | hard | SemVer 2.0 precedence and npm-style ranges (`^ ~ x-ranges \|\|`) |
| `scheduler` | hard | deterministic topological order, cycles, critical path, worker simulation |
| `calc` | hard | replace `eval` with a safe, exact expression parser |

`reset(seed)` is deterministic: the same seed gives byte-identical files and the same state hash (checked on
every baseline run and logged); a different seed changes parameters in code, README, visible tests and hidden
checks (tiers, separators, gaps, capacities, names, random inputs).

## Reward (programmatic only)

Hidden checks are split into **target** checks (fail on the starting code) and **regression** checks (pass on it).
The split is computed when the task is built by running every check against the starting code, so a check that
pays out for doing nothing cannot exist.

```
tests_passed      = 0.7 x share of target checks passed
no_regressions    = 0.3 x target share x share of regression checks passed   (scaled by progress: doing nothing earns 0)
integrity_penalty = -0.3 if existing visible tests were changed or a check result was spoofed
total             = max(0, sum)
```

Comparison is meaningful, not textual: numbers by value (with tolerance for floats), tuples equal lists, exceptions
checked by type, and checks execute the agent's code and compare returned values rather than printed text.

## Isolation

- **Two containers.** `sandbox` runs the agent's tools; `harness` holds the verifier, expected values, hidden
  check code, reference solutions and reward code. The sandbox image does not contain them, and the harness
  has no shared volume with it.
- **No network for the agent.** The sandbox is only on an `internal: true` Docker network (no route out).
  Only the harness is also attached to the network that can reach the model API. Dependencies are installed at
  build time.
- **Unprivileged tool processes.** The sandbox server runs as root only to drop every tool and check process to
  uid 1001 with CPU, memory, file-size, process-count and open-file limits, new session, whole process group killed
  after each call, leftover processes killed before the final score. The server code lives in a `0700` directory
  and is unreadable and un-signalable by the agent; `cap_drop: ALL` plus only the capabilities needed to demote.
- **Hidden checks are sent as code at scoring time** to a throwaway copy of the workspace, run in a fresh process
  per check with `-P -s` (no `sitecustomize` pickup), and only the returned value comes back; the expected value
  stays in the harness. Check results travel inside a one-time random marker, so printing a fake result is
  detected and penalised.
- **Visible tests are read-only** through the file tools and integrity-checked by hash at scoring.

## Robustness for any model

- One OpenAI-compatible interface (`MODEL`, `API_KEY`, `BASE_URL`); nothing special-cases a model or the appended file.
- Tolerant parsing: invalid or double-encoded JSON arguments, argument aliases (`file_path`, `old_str`), wrong
  JSON types, namespaced tool names (`functions.read_file`), extra arguments, more than 10 calls, unknown tools,
  empty replies, and tool calls written as text (JSON blocks, `<tool_call>` tags) when a model does not emit native
  calls. Every problem returns a clear error to the agent and the run continues; an unreadable reply still costs a step.
- If an endpoint rejects `tools`, the client switches to text tool calls; `max_tokens` falls back to
  `max_completion_tokens`.
- Context: tool output cut at 4000 characters, history trimmed (old outputs, old arguments, old turns) to a pessimistic
  40K-token estimate, one automatic retry with a tighter budget on a context-overflow error.
- Limits as in the brief: 40 replies, 10 minutes from the first model request, 10 tool calls per reply, 60 s per tool
  call (tools stop themselves at 20 s / 30 s), 2 minute verifier budget (90 s enforced).
- Termination is always recorded: `success`, `failure`, `step_cap`, `time_cap` or `crash`.

## Telemetry

`episode.jsonl` has one line per reply with `timestamp, step, seed, model_input, model_output_raw, parsed_actions,
tool_result, errors, state (hash, files_changed), reward (components + total), tokens, latency_ms` plus `flags`.
Suspicious behaviour is flagged live, never silently: `network_attempt`, `sandbox_probe`, `verifier_probe`,
`path_escape_attempt`, `process_or_privilege`, `introspection_or_patching`, `dynamic_code_execution`,
`test_tampering_blocked`, `blocked_access_observed`, `repetitive_calls`. The final `episode_end` line carries the
verifier output (passed/failed checks, tampering, changed protected files) and flag counts.

## Offline self-checks

```bash
pip install -r requirements.txt
python -m unittest tests.test_tasks       # reference passes every hidden check, starting code earns nothing, 8 seeds
```

Offline models for demos and tests: `mock/solver`, `mock/idle`, `mock/cheater` (probes the sandbox, edits tests),
`mock/chaos` (bad JSON, unknown tools, 11 calls, aliases), `mock/text` (text-only tool calls), `mock/loop` (step cap).

## Layout

```
docker-compose.yml  Dockerfile.sandbox  Dockerfile.harness  requirements.txt  .env.example  check_model.py
sandbox/server.py    tools run as an unprivileged user; /reset /tool /verify /state
harness/run.py       oracle, then no-op, then the model; modes; exit codes
harness/runner.py    step loop, limits, context trimming, telemetry
harness/env.py       reset / step / score: the verifier and reward
harness/tools.py     tool schemas and tolerant argument handling
harness/agents.py    OpenAI client, text-call parser, mock models, baselines
harness/monitor.py   suspicious-behaviour flags
harness/tasks/       the nine tasks (starting code, reference, hidden checks, generators)
tests/               offline self-checks
```

## Known weaknesses

- The agent's code runs in the same process as a hidden check, so it could print or crash instead of returning a
  value; it cannot know the expected value, spoofed output is detected, and a crash scores as a failed check.
- A guessable boolean check could be satisfied by luck; most checks compare structured values over generated inputs.
- Hard-coding visible examples is possible but scores nothing on the hidden, seeded inputs.
- Final scoring kills the agent's background processes; per-step scoring uses a copy and does not.
