# RP Native I/O Protocol Specification

This document specifies the structured I/O protocol between `aiwf` and a RepoPrompt (RP) native runtime binary.

**Status:** Design specification — not yet implemented in runtime code.

**Audience:** RP runtime implementors, aiwf adapter maintainers, integration authors.

**Canonical code references:**

- Current subprocess invocation: `src/aiwf/adapters/rp_agent.py` → `_run_rp()`
- Native runtime contract model: `src/aiwf/adapters/base.py` → `NativeRuntimeContract`
- RP contract defaults: `src/aiwf/adapters/rp_agent.py` → `RP_NATIVE_RUNTIME`, `RP_AUTO_CONTRACT`
- Compatibility policy: `docs/compatibility-policy.md`
- Install/integration guide: `docs/INSTALL_GUIDE.md`

---

## 1. Problem Statement

The current RP auto execution path (`_run_rp()`) communicates with the RP runtime via raw text:

- **Request:** UTF-8 prompt text piped to the runtime's stdin.
- **Response:** UTF-8 text captured from stdout; empty stderr + returncode 0 = success.
- **Errors:** Non-zero returncode; error message taken from stderr (falling back to stdout).
- **Timeout:** Subprocess-level timeout (default 300s) raises `AdapterError`.

This works for basic execution but has fundamental limitations:

1. **No structured errors.** The adapter cannot distinguish "syntax error in prompt" from "internal runtime crash" from "task too large."
2. **No metadata round-trip.** Stage name, run context, timeout preferences, and capability flags cannot be communicated to the runtime.
3. **No partial results.** If the runtime fails mid-execution, all output is lost.
4. **No capability negotiation.** The adapter cannot discover which protocol version or features the runtime supports.
5. **No progress signaling.** Long-running stages provide no feedback until completion or timeout.

This spec defines a structured envelope protocol that resolves these gaps while preserving backward compatibility with runtimes that only speak legacy text mode.

---

## 2. Design Principles

1. **Backward compatible by default.** A protocol-aware `aiwf` must still work with a legacy text-only RP runtime. A protocol-aware runtime should degrade gracefully when invoked by an older `aiwf`.
2. **JSON envelope, not a new transport.** The protocol stays on stdin/stdout/stderr over subprocess. No sockets, no HTTP, no IPC files.
3. **Additive evolution.** New fields are optional with documented defaults. Removing or renaming fields is a breaking change governed by `docs/compatibility-policy.md`.
4. **aiwf is the caller; RP runtime is the callee.** The adapter controls invocation, timeout, and retry. The runtime is a stateless command that processes one request per invocation.

---

## 3. Capability Detection

Before sending a structured request, `aiwf` must determine whether the runtime supports the envelope protocol.

### 3.1 Detection command

```
<rp-command> --aiwf-protocol-version
```

- **Exit code 0** + stdout containing a valid JSON object → runtime supports structured protocol.
- **Exit code non-zero** or unrecognized output → runtime is legacy text-only.

### 3.2 Detection response shape

```json
{
  "protocol": "aiwf-rp-native",
  "version": 1,
  "capabilities": []
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `protocol` | string | yes | Must be `"aiwf-rp-native"`. |
| `version` | integer | yes | Protocol version the runtime supports. This spec defines version `1`. |
| `capabilities` | string[] | yes | Optional capability tokens for future extensions (e.g. `"streaming"`, `"partial-result"`). Version 1 defines no required capabilities; the list may be empty. |

### 3.3 Caching

The adapter should cache the detection result for the lifetime of a single `aiwf` process (or a single run). Re-detection on every stage call is unnecessary overhead.

### 3.4 Fallback

If detection fails or returns an unrecognized `protocol` string, the adapter falls back to legacy text mode (current `_run_rp()` behavior) for all stages in that run.

---

## 4. Request Envelope

When the runtime supports protocol version ≥ 1, the adapter sends a JSON object on stdin instead of raw prompt text.

### 4.1 Top-level request shape

```json
{
  "protocol": "aiwf-rp-native",
  "version": 1,
  "request_type": "execute",
  "stage": "implement",
  "prompt": "Task: Example task\n\nImplement the approved plan...",
  "context": {
    "run_id": "20260416-abcdef",
    "run_dir": ".ai/runs/20260416-abcdef",
    "task_title": "Add retry backoff to gate runner",
    "task_slug": "add-retry-backoff-to-gate-runner",
    "adapter": "rp",
    "mode": "auto"
  },
  "options": {
    "timeout_seconds": 300
  },
  "metadata": {}
}
```

### 4.2 Field reference

| Field | Type | Required | Description |
|---|---|---|---|
| `protocol` | string | yes | Must be `"aiwf-rp-native"`. |
| `version` | integer | yes | Protocol version of this request. |
| `request_type` | string | yes | One of: `"plan"`, `"execute"`, `"review"`. Maps directly to adapter stage methods. |
| `stage` | string | yes | The aiwf workflow stage name (e.g. `"plan"`, `"implement"`, `"review"`). Typically matches `request_type` but kept separate for future flexibility (e.g. custom stages). |
| `prompt` | string | yes | The full prompt text that would have been sent as raw stdin in legacy mode. This preserves content compatibility — the runtime can ignore the envelope and process only `prompt` if desired. |
| `context` | object | yes | Run context metadata (see §4.3). |
| `options` | object | no | Caller-side hints (see §4.4). Runtime may ignore any option it does not recognize. |
| `metadata` | object | no | Opaque pass-through object for future extensions. Runtime must preserve and return it in the response if present. |

### 4.3 Context object

| Field | Type | Required | Description |
|---|---|---|---|
| `run_id` | string | yes | The aiwf run identifier. |
| `run_dir` | string | yes | Relative path to the run directory (from repo root). |
| `task_title` | string | yes | Human-readable task title. |
| `task_slug` | string | yes | Filesystem-safe task slug. |
| `adapter` | string | yes | Always `"rp"` for this protocol. |
| `mode` | string | yes | Always `"auto"` when using this protocol (manual mode does not invoke the runtime). |

### 4.4 Options object

All options are advisory. The runtime may ignore any it does not support.

| Field | Type | Default | Description |
|---|---|---|---|
| `timeout_seconds` | integer | 300 | Suggested timeout. The subprocess-level timeout in `aiwf` is the hard boundary; this hint lets the runtime set its own internal deadline slightly shorter to allow graceful shutdown. |
| `max_output_bytes` | integer | null | If set, a soft hint on maximum response size. |

---

## 5. Response Envelope

The runtime writes a JSON object to stdout on success or structured failure.

### 5.1 Successful response

```json
{
  "protocol": "aiwf-rp-native",
  "version": 1,
  "status": "ok",
  "content": "# Implementation Plan\n\n...",
  "metadata": {},
  "diagnostics": null
}
```

### 5.2 Error response

```json
{
  "protocol": "aiwf-rp-native",
  "version": 1,
  "status": "error",
  "content": null,
  "error": {
    "code": "PROMPT_TOO_LARGE",
    "message": "Input prompt exceeds the runtime's context window (128k tokens).",
    "retriable": false,
    "detail": {}
  },
  "metadata": {},
  "diagnostics": null
}
```

### 5.3 Partial result response

When the runtime fails after producing partial output, it may return a partial result so `aiwf` can record what was accomplished:

```json
{
  "protocol": "aiwf-rp-native",
  "version": 1,
  "status": "partial",
  "content": "# Partial output before failure\n\n...",
  "error": {
    "code": "EXECUTION_INTERRUPTED",
    "message": "Runtime interrupted after producing partial output.",
    "retriable": true,
    "detail": {}
  },
  "metadata": {},
  "diagnostics": null
}
```

### 5.4 Field reference

| Field | Type | Required | Description |
|---|---|---|---|
| `protocol` | string | yes | Must be `"aiwf-rp-native"`. |
| `version` | integer | yes | Protocol version of this response. |
| `status` | string | yes | One of: `"ok"`, `"error"`, `"partial"`. |
| `content` | string or null | yes | The response text. For `"ok"`: the full response (equivalent to what legacy mode returns on stdout). For `"partial"`: whatever was produced before failure. For `"error"` with no output: `null`. |
| `error` | object or null | conditional | Required when `status` is `"error"` or `"partial"`. Must be `null` or absent when `status` is `"ok"`. See §6. |
| `metadata` | object | no | Round-tripped from the request `metadata` field, plus any runtime-added entries. |
| `diagnostics` | object or null | no | Optional runtime diagnostics (timing, token counts, model info) for observability. No schema enforced in v1; treated as informational. |

---

## 6. Error Object

### 6.1 Shape

```json
{
  "code": "ERROR_CODE",
  "message": "Human-readable error description.",
  "retriable": false,
  "detail": {}
}
```

### 6.2 Field reference

| Field | Type | Required | Description |
|---|---|---|---|
| `code` | string | yes | Machine-readable error code. See §6.3 for defined codes. |
| `message` | string | yes | Human-readable description. May be shown to operators. |
| `retriable` | boolean | yes | Whether `aiwf` should consider retrying the same request. |
| `detail` | object | no | Arbitrary structured context for debugging. No schema enforced. |

### 6.3 Defined error codes (v1)

| Code | Meaning | Retriable default |
|---|---|---|
| `PROMPT_TOO_LARGE` | Input exceeds runtime capacity. | `false` |
| `EXECUTION_TIMEOUT` | Runtime's internal timeout fired before producing a result. | `true` |
| `EXECUTION_INTERRUPTED` | Execution was interrupted (e.g. signal, user cancel). | `true` |
| `RUNTIME_ERROR` | Unrecoverable internal error in the runtime. | `false` |
| `INVALID_REQUEST` | The request envelope was malformed or missing required fields. | `false` |
| `UNSUPPORTED_VERSION` | The requested protocol version is not supported by this runtime. | `false` |
| `UNKNOWN` | Catch-all for errors that don't fit other codes. | `false` |

Runtimes may emit codes not in this list. The adapter must treat unrecognized codes as non-retriable unless `retriable` is explicitly `true`.

---

## 7. Exit Code Semantics

Exit codes complement the response envelope. They are the primary signal when the runtime cannot produce a valid JSON response.

| Exit code | Meaning | Adapter behavior |
|---|---|---|
| `0` | Success or structured response written to stdout. | Parse stdout as JSON envelope. If parsing fails, treat stdout as legacy text response. |
| `1` | Structured error response written to stdout. | Parse stdout as JSON envelope. If parsing fails, use stderr or stdout as legacy error message. |
| `2` | Runtime could not produce any response (crash, OOM, etc.). | Use stderr text as error message. Map to `AdapterError`. |
| Other | Unspecified. | Treat as exit code 2. |

**Key rule:** Exit code 0 with a valid JSON envelope whose `status` is `"error"` is valid — it means the runtime handled the error gracefully and chose to report it structurally rather than via exit code. The adapter should prefer the envelope's `error` object over the exit code for classification.

---

## 8. Legacy Text Mode Compatibility

### 8.1 When aiwf detects a legacy runtime

If capability detection (§3) fails, the adapter uses the current `_run_rp()` behavior unchanged:

- Send raw prompt text on stdin (not JSON).
- Read raw response text from stdout.
- Non-zero returncode → `AdapterError` with stderr/stdout as message.

No code changes are needed for legacy runtimes. This path must remain functional indefinitely.

### 8.2 When a protocol-aware runtime receives legacy input

A protocol-aware runtime receiving non-JSON stdin (i.e. raw text that does not parse as a JSON object with `"protocol": "aiwf-rp-native"`) should treat the entire stdin as a legacy prompt and respond with raw text on stdout, matching current behavior.

This makes the runtime backward-compatible with older `aiwf` versions or manual invocation.

### 8.3 Detection heuristic for the runtime

The runtime can detect input mode by checking whether stdin begins with `{` and parses as a JSON object containing `"protocol": "aiwf-rp-native"`. If not, treat all stdin as a raw text prompt.

---

## 9. Adapter Integration Outline

This section sketches how `_run_rp()` in `rp_agent.py` should evolve. It is guidance for implementors, not a binding API spec.

### 9.1 Initialization

On first RP auto invocation in a run, call the detection command (§3). Cache the result.

### 9.2 Stage execution

```
if runtime supports protocol:
    build request envelope (§4)
    write JSON to stdin
    read stdout
    parse as JSON envelope (§5)
    if status == "ok":
        return content
    elif status == "partial":
        write partial content to artifact as best-effort
        raise AdapterError with error.code + error.message
    elif status == "error":
        raise AdapterError with error.code + error.message
    if JSON parse fails:
        fall back to legacy text interpretation
else:
    current _run_rp() behavior unchanged
```

### 9.3 Timeout handling

The subprocess-level timeout in `aiwf` remains the hard boundary. The `options.timeout_seconds` hint in the request envelope lets the runtime set a softer internal deadline to produce a graceful `"partial"` or `"error"` response instead of being killed.

### 9.4 NativeRuntimeContract evolution

`NativeRuntimeContract` should gain a `protocol_version` field:

```python
@dataclass(frozen=True)
class NativeRuntimeContract:
    enabled: bool = False
    command_candidates: tuple[str, ...] = ()
    install_hint: str | None = None
    protocol_version: int | None = None  # NEW: detected at runtime, not persisted
```

`protocol_version` is populated by detection (§3) and used for dispatch. It is **not** persisted in `run.json` because it describes the runtime environment, not the run contract. If future needs require persistence, it should follow `docs/compatibility-policy.md` §4.4 additive-field rules.

---

## 10. Versioning Strategy

### 10.1 Protocol version semantics

- Version `1` is defined by this document.
- A new version is required when: a required field is added, a field is removed or renamed, or the meaning of an existing field changes.
- A new version is **not** required for: adding optional fields, adding new error codes, or adding capability tokens.

### 10.2 Version negotiation

The adapter sends a `version` field in the request. If the runtime does not support that version, it returns an error response with code `UNSUPPORTED_VERSION` and includes the highest version it supports in `error.detail.supported_version`.

```json
{
  "protocol": "aiwf-rp-native",
  "version": 1,
  "status": "error",
  "content": null,
  "error": {
    "code": "UNSUPPORTED_VERSION",
    "message": "This runtime supports protocol version 2; received version 1.",
    "retriable": false,
    "detail": {
      "supported_version": 2
    }
  }
}
```

The adapter should not attempt automatic downgrade negotiation in v1. If version mismatch occurs, fall back to legacy text mode and surface a warning to the operator.

### 10.3 Forward compatibility

Runtimes must ignore unrecognized top-level request fields (future optional additions). Adapters must ignore unrecognized top-level response fields. This ensures additive changes do not require version bumps.

---

## 11. Security Considerations

- **No shell expansion.** The runtime is invoked as a direct subprocess (not `shell=True`). The protocol does not change this.
- **Prompt injection boundary.** The `prompt` field contains user/task-originated content. The runtime must treat it as untrusted input — exactly as it treats raw stdin today.
- **No credential passing.** The protocol does not define fields for secrets, tokens, or credentials. If the runtime needs authentication, it should use environment variables or a config file, not the request envelope.
- **Response size.** The adapter should enforce a reasonable maximum on stdout capture to prevent OOM from a misbehaving runtime. The existing subprocess `capture_output=True` behavior applies.

---

## 12. Future Extensions (Out of Scope for v1)

The following are **not** part of this specification but are anticipated directions:

- **Streaming responses.** A `"streaming"` capability token could enable line-delimited JSON progress events on stdout before the final response.
- **Multi-turn interaction.** The current protocol is single request/response per invocation. A future version could support follow-up rounds within a single subprocess session.
- **File-based I/O.** For very large prompts or responses, a future version could support passing content via temporary files referenced in the envelope, rather than inline in `prompt`/`content`.
- **Binary/structured artifacts.** The `content` field is text. A future capability could allow structured artifact objects in the response.

---

## 13. Compatibility Policy Alignment

This protocol follows the principles in `docs/compatibility-policy.md`:

- **Additive first.** All new fields introduced by the protocol are additive to the existing adapter contract surface.
- **No silent breakage.** The adapter's legacy text path is untouched and remains the default when detection fails.
- **NativeRuntimeContract changes.** Adding `protocol_version` to `NativeRuntimeContract` is an additive field with a `None` default. Per §4.4 of the compatibility policy, this does not require a schema version bump, but projection fixture updates are needed if the field appears in the compat view.
- **Projection contract bump.** When the implementation lands, `rp-host-projection-v1` should bump to `rp-host-projection-v2` because the native runtime section of the RP projection gains a new stable field (`protocol_version` or protocol detection semantics).

---

## 14. Acceptance Criteria for Implementation

When this protocol is implemented, the following must hold:

1. `_run_rp()` detects runtime protocol support via `--aiwf-protocol-version`.
2. Protocol-aware requests use the JSON envelope; legacy runtimes receive raw text — no behavioral change.
3. A mock RP runtime implementing protocol v1 passes the full implement→review flow with structured error recovery.
4. `AdapterError` raised from protocol errors carries the `error.code` for downstream structured diagnostics.
5. Legacy text-mode RP runtimes continue to work identically — all existing RP adapter tests pass without modification.
6. `doctor` reports detected protocol version when checking RP runtime availability.
7. Projection compat fixtures are updated and `tests/test_compile.py` + `tests/test_adapter_contracts.py` pass.
