# Validation report: solution vs the hackathon PDF

Date: 2026-10-23

**Verdict:** the solution meets every minimum-spec item the PDF lists except the Docker items, which could not be run. Docker is not installed on the test machine, so the sandbox ran as a plain Python process on Windows. The Docker-specific items below are unverified.

## 1. Minimum spec checklist (section 03)

| Requirement | Status | Evidence |
|---|---|---|
| Task definition with success criteria | Pass | Each task has an instruction plus a README spec ([harness/tasks/](harness/tasks/)). |
| Observation | Pass | `Env.reset` returns the task and file list. Each tool result carries a step and time footer. |
| Tool space with name, description and schema | Pass | 8 tools in [harness/tools.py](harness/tools.py). |
| State that persists | Pass | Edits persist in the sandbox workspace. The state hash and `files_changed` are logged per step. |
| Seeded reset | Pass | Seed 7 gives `574f0280` both times, seed 8 gives `ae9047db`, and `reset_ok=True`. The unit test passes for 8 seeds. |
| Termination with reason | Pass | `success`, `failure`, `step_cap`, `time_cap` and `crash` are all implemented. Success, failure and step_cap were observed in runs. |
| Programmatic verifier with partial credit | Pass | Hidden checks run as code, and the reward is 0.7 target + 0.3 target x regression - 0.3 integrity penalty. No LLM is used. |
| 5 or more tasks across 2 or more levels | Pass | 9 tasks: 3 easy, 3 medium, 3 hard. |
| Demo task named in the README | Pass | `slugify`. |
| Reference solution and no-op baseline per task | Pass | See section 2. |
| Isolation | Designed, not run under Docker | See section 4. |
| One Docker Compose command, build within 3 min, pinned deps | Not run | [docker-compose.yml](docker-compose.yml) and both Dockerfiles are written. All dependencies are pinned, including transitive ones. |

## 2. Baselines (section 04)

`MODE=baselines` across all nine tasks completed with "all checks passed":

| Task | Oracle | No-op | Deterministic reset |
|---|---|---|---|
| slugify | 1.00 | 0.00 | yes |
| pricing | 1.00 | 0.00 | yes |
| intervals | 1.00 | 0.00 | yes |
| ttl_cache | 1.00 | 0.00 | yes |
| csv_report | 1.00 | 0.00 | yes |
| ledger | 1.00 | 0.00 | yes |
| semver | 1.00 | 0.00 | yes |
| scheduler | 1.00 | 0.00 | yes |
| calc | 1.00 | 0.00 | yes |

- **Pass thresholds:** the oracle must score at least 0.95 and the no-op at most 0.05, and both held on every task.
- **Earlier failures:** the first run had no-op scores of 0.06 (`slugify`) and 0.04 (`scheduler`). Both were checks the starting code happened to pass.
- **Fix:** every hidden check is now run against the starting code when the task is built. A target check can no longer pay out for doing nothing.
- **Offline suite:** `python -m unittest tests.test_tasks` passes. For each of 8 seeds per task it confirms the reference passes every hidden check, the starting code earns zero on target checks, the visible tests pass with the reference, and the same seed gives the same files.
- **Results file:** gate results are saved in `logs/20261023-135047/gate.json`.

## 3. Harness and model-agnostic behaviour (sections 05 and 06)

| Requirement | Status | Evidence |
|---|---|---|
| `MODEL`, `API_KEY`, `BASE_URL`, `TASK_ID`, `SEED`, `MODE` from `.env` | Pass | The harness reads them from the environment. |
| `APPEND_FILE` appended to the system prompt exactly as given and logged | Pass, with one bug fixed | The text is correct at the end of the system prompt and the sha256 is logged. On Windows the saved copy `append.txt` had CRLF newlines instead of LF. This was fixed in [harness/run.py](harness/run.py) and not re-run. Linux was not affected. |
| Missing, empty or bad config stops the run | Pass | Missing file, empty file, bad `MODE`, bad `TASK_ID` and a real model with no key each exit with code 3. |
| Robust parsing | Pass | The chaos mock sends bad JSON, an unknown tool, 11 calls, a namespaced name and extra arguments. It still finished with `success` in 7 steps. |
| Text-only tool calls | Pass | The text mock succeeded in 2 steps. |
| 40-step cap | Pass | The loop mock ended with `step_cap` at 40 steps. |
| 10-minute cap, 10 calls per reply, 60 s per tool, 2 min verifier | Implemented | The sandbox stops tools at 20 s and 30 s, and the verifier budget is 90 s. |
| Context handling for 64K models | Implemented, not stress-tested with a real model | Tool output is cut at 4000 characters, old turns are trimmed, and there is one retry on a context-overflow error. |
| Works with GPT-Luna and the undisclosed model | Not tested | No API key was available. The OpenAI-compatible client is written to the PDF's call shape. |

## 4. Isolation (section 04)

- **Not exercised in Docker.** The two-container split, the internal no-internet network, `cap_drop: ALL`, and the drop to an unprivileged user have not been confirmed under Docker.
- **Locally verified:**
  - The cheater mock's test edit via the file tool was blocked.
  - Its other test modifications were caught and penalised (-0.3).
  - Its sandbox and network probes were flagged.
- **Remaining check:** after running under Docker, run `MODEL=mock/cheater` and confirm the network attempt and the `/opt/sandbox` read fail rather than just being flagged.

## 5. Telemetry (section 07)

- **Step lines:** every step has all 12 required fields.
- **Episode end:** the final line has `termination` and `verifier`.
- **Baselines:** baseline checks are logged the same way.
- **Live flags:** nine kinds of suspicious behaviour are flagged and printed per step.
- **Terminal stream:** a readable stream is printed.
- **Observed on the cheater mock:** `sandbox_probe`, `network_attempt`, `test_tampering_blocked`.
- **Observed on the loop mock:** `repetitive_calls`.

## 6. Gaps and risks

1. **Docker is unverified.** This covers the 3-minute build limit, the sandbox network block, the privilege drop and the real healthcheck. Install Docker (the README has the steps), run the one-command flow, and re-run `MODE=baselines` there.
2. **Baseline speed.** A single task's checks took 37-47 s on Windows, because each hidden check starts a fresh Python process. That fits the 2-minute limit, but Linux timing is unmeasured.
3. **No real-model run yet.** The zip needs logs from at least 3 of your own model runs, including at least one success and one failure. `check_model.py` is ready for your GPT-Luna credentials.
4. **Known weakness.** Agent code runs in the same process as a hidden check, so it could spoof output. It cannot know the expected value, and spoofed output is detected and penalised.
5. **Submission items not produced here:** `design-doc.pdf`, `deck.pdf`, a private GitHub repo named after your team, and the organiser invite.

## 7. What to do next

1. Install Docker, then run `MODE=baselines docker compose up --build --abort-on-container-exit --exit-code-from harness`. Check the build time against the 3-minute limit.
2. Run `MODEL=mock/cheater` there to confirm the isolation actually blocks, not just flags.
3. Put your GPT-Luna details in `.env`, run `python check_model.py`, then run `MODE=all` for the model logs.
4. Run `MODE=baselines` again under Docker and keep `gate.json` for the zip.
