# RP Real Runtime Validation

This document explains how to interpret `aiwf` RP conformance/doctor signals once bridge work is complete.

## Why this doc exists

`aiwf` can validate its RP-native protocol logic against the in-repo reference harness (`rp-cli-stub` and fake runtime scripts), but that is **not** the same thing as proving that the real RepoPrompt product runtime supports `aiwf-rp-native/v1`.

Phase 6 adds explicit scope labels so operators do not over-read a passing stub run as product certification.

## Scope labels

`aiwf conformance rp` now always emits one of these scopes:

| Scope | Meaning |
| --- | --- |
| `reference-stub` | The validated command matches aiwf's stub/fake-runtime heuristics. This is repo confidence only. |
| `real-runtime-untrusted` | The command looks non-stub-like, but aiwf has **not** promoted the result to certification. Treat it as an operator observation. |
| `real-runtime-certified` | A non-stub-like runtime passed conformance and the operator explicitly promoted that report with `--certify-real-runtime`. |

## Recommended operator procedure

### 1. Confirm which binary you are testing

Typical product target:

```bash
/usr/local/bin/rp-cli
```

On machines where RepoPrompt.app is installed, this may resolve to the app bundle runtime (for example `/Applications/Repo Prompt.app/.../repoprompt-mcp`).

### 2. Run doctor first

```bash
uv run aiwf doctor --json
```

Look at the `rp` and `rp-bridge` checks:

- `runtime_detection=stub-like` means the binary matched aiwf's **heuristics** for a reference harness or current Python-environment binary.
- `runtime_detection=non-stub-like` means the binary did **not** match those heuristics.
- `rp-bridge` probe `available=true` means the CLI appears to support MCP tool invocation capability; it is not a provider certification signal.

This is intentionally heuristic only. It is a labeling aid, not proof of product identity.

### 3. Run conformance against the real candidate

```bash
uv run aiwf conformance rp --rp-command /usr/local/bin/rp-cli --json
```

Interpret the result conservatively:

- `scope=reference-stub` => you validated the repo reference harness, not the product runtime.
- `scope=real-runtime-untrusted` => you exercised a non-stub-like binary, but aiwf is still not claiming certification.
- `scope=real-runtime-certified` should appear **only** if you explicitly opt in with `--certify-real-runtime` after reviewing the output.

### 4. Promote to certified only after explicit review

If the runtime is non-stub-like and all conformance checks pass, you may record a certified report:

```bash
uv run aiwf conformance rp \
  --rp-command /usr/local/bin/rp-cli \
  --certify-real-runtime \
  --json
```

Use this only after confirming:

1. the tested binary is the intended RepoPrompt product/runtime,
2. the `probe`, request/response, and legacy checks all passed, and
3. you are comfortable treating that exact binary/version as your certified target.

## Expected failure points

Per `docs/RP_PROVIDER_GAP_ANALYSIS.md` §§1–3, the current real RepoPrompt CLI is expected to fail native-provider certification in common environments because:

1. it exposes a workspace/agent orchestration CLI rather than a single-shot provider subprocess envelope,
2. its transport/response model may not match `aiwf-rp-native/v1`, and
3. bridge capability detection is about MCP tool invocation readiness, not native-provider protocol compatibility.

If that happens, the correct interpretation is:

- keep certification posture at `reference-stub`, and
- use the **bridge** path as the supported RP integration.

Also note: a green bridge probe does not guarantee every tool is available at runtime (for example `agent_run` / `agent_manage` can still be unavailable and should be handled via manual-assist fallback).

## Decision rule

If the real runtime probe fails or the conformance run does not pass cleanly:

- do **not** promote the runtime to `real-runtime-certified`,
- do **not** treat native RP auto/provider mode as supported product behavior, and
- continue using `--bridge` / manual-assist / managed-agent flows as the supported integration path.

As of P7–P10 landing (2026-04-17), bridge orchestration now includes richer session recovery, context composition/oracle advisory surfaces, read-only exploration, and gated destructive transports. That does **not** change this certification rule: bridge capability/readiness and native-provider certification remain separate signals.

## Heuristic notes for doctor

Current `doctor` labels a detected binary as `stub-like` when it matches signs such as:

- `rp-cli-stub` / `rp_cli_stub` paths,
- aiwf fake runtime / fake bridge harness file names, or
- `rp` / `rp-cli` binaries discovered inside the current Python environment / virtualenv.

Everything else is labeled `non-stub-like`.

That label is intentionally conservative: it helps the operator avoid false confidence, but it does **not** prove a binary is the official RepoPrompt runtime.
