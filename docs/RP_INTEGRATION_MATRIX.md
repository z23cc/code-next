# RP Integration Matrix

Decision-oriented view of current RP integration posture across three layers:

1. **aiwf core**
2. **RP runtime/provider** (`rp` / `rp-cli`)
3. **RepoPrompt/plugin/project-consumer surfaces**

This doc is intentionally concise and repo-grounded. For detailed evidence and per-layer inventories, see:

- `docs/RP_CAPABILITY_INVENTORY.md`
- `docs/REPOPROMPT_CAPABILITY_INVENTORY.md`
- `docs/RP_REAL_RUNTIME_VALIDATION.md`

## Status legend

| Mark | Meaning |
| --- | --- |
| **IV** | Implemented + validated |
| **IA** | Implemented + assumed |
| **DO** | Documented-only |
| **Gap** | Not implemented or not evidenced |

## Evidence anchors

Primary sources behind this matrix:

- Runtime/protocol: `src/aiwf/adapters/rp_agent.py`, `docs/RP_NATIVE_PROTOCOL.md`, `tools/rp-cli-stub/src/rp_cli_stub/cli.py`
- Contracts/restore: `src/aiwf/adapters/base.py`, `src/aiwf/adapters/__init__.py`, `src/aiwf/contracts.py`
- Diagnostics/conformance: `src/aiwf/doctor.py`, `src/aiwf/conformance.py`
- Projection/install surfaces: `src/aiwf/compilers/rp.py`, `src/aiwf/compilers/base.py`, `docs/compatibility-policy.md`, `docs/INSTALL_GUIDE.md`
- Validation and confidence boundaries: `tests/test_adapter_rp.py`, `tests/test_adapter_contracts.py`, `tests/test_compile.py`, `tests/test_doctor.py`, `tests/test_conformance_rp.py`, `tests/test_cli.py`, `.github/workflows/ci.yml`, `.github/workflows/release-check.yml`, `.github/workflows/testpypi-release.yml`

## Three-layer capability mapping matrix

| Capability | aiwf core | RP runtime / provider | RepoPrompt / plugin / consumer | Decision note |
| --- | --- | --- | --- | --- |
| Protocol detection (`--aiwf-protocol-version`) | **IA** — probe + caching implemented and tested via fake runtime/stub | **DO** — spec + stub define expected payload; no real-runtime proof | **IA** — `doctor`/CI surface detection signals, but only stub-backed | aiwf is ready to negotiate; real RP support is still unverified. |
| Structured request envelope | **IA** — request JSON built and exercised in adapter tests | **DO** — spec and stub define request handling | **Gap** — no consumer surface beyond runtime itself | Good internal readiness; blocked on real runtime implementation proof. |
| Structured response handling (`ok` / `error` / `partial`) | **IA** — parser/error mapping implemented; `partial` covered by fake runtime test | **DO** — stub covers `ok`/`error`; real runtime unknown; `partial` not proven in stub | **IA** — auto response artifacts depend on this path | Internal handling is ahead of certified provider support. |
| Legacy raw-text fallback | **IA** — probe failure and unsupported-version fallback implemented | **DO** — expected by spec and stub behavior | **DO** — only indirectly consumable as native fallback behavior | Backward-compat path exists, but still not certified against real RP binaries. |
| Manual handoff workflow | **IV** — default RP path, prompt artifacts, resume flow, stored contract restore all tested | **DO** — no native runtime requirement | **IV** — human-operator flow is documented and exercised by CLI tests | This is the strongest, production-like RP path in the repo today. |
| Bridge — manual-assist groundwork | **IV** — bridge contract, persisted `rp_bridge`, CLI/inspect/doctor surfacing, and manual prompt enrichment are implemented/tested | **DO** — relies on the real RP app / MCP CLI being the eventual bridge target; no MCP/tool invocation yet | **DO** — docs describe the operator-facing groundwork, but no RP-side consumer automation exists yet | Groundwork is in place without changing the stable manual handoff path. |
| Auto/native execution path | **IA** — adapter, artifacts, and entrypoints exist | **DO** — official target is real RP runtime, but no real-runtime validation | **IA** — consumers can read response artifacts if native path works | Exists as an experimental path, not as a certified integration. |
| Host contract persistence and resume semantics | **IV** — `host_contract` persistence/restore and native runtime backfill are fixture-protected | **DO** — runtime need only honor surfaced mode/runtime expectations | **IV** — projection and run metadata expose stable consumer-facing semantics | Strong stable contract surface for downstream readers. |
| Review evidence contract | **IV** — manual/auto report contracts and evidence checks are implemented/tested | **DO** — runtime only indirectly affects auto response generation | **IV** — consumers can rely on required artifacts and linked artifact fields | One of the most mature cross-surface contracts in the repo. |
| RP projection (`rp-projection.json`) | **IV** — compile output and compat fixture lock the schema | **DO** — runtime assumptions embedded as contract metadata | **DO** — no real RepoPrompt-side consumer reads it in-repo | Stable producer surface; unvalidated consumer uptake. |
| Install surface (`install-surface.json`) | **IV** — output directory ownership semantics are tested and policy-backed | **DO** — runtime not directly involved | **DO** — docs describe consumption; no external consumer test | Strong emitted contract, weak consumer evidence. |
| Bundle + manifest outputs | **IV** — bundle content, manifest hashes, drift status are tested | **DO** — runtime not directly involved | **DO** — human/operator usage documented; no external automation proof | Good producer story; no real downstream adoption evidence. |
| Doctor readiness signal | **IV** — JSON fields and warning/ok logic are implemented/tested, including stub-like vs non-stub-like runtime heuristics | **DO** — meaningful only if PATH binary is the real RP runtime | **IA** — CI/operator can read it, but the heuristic is intentionally non-authoritative | Useful as a readiness hint, not as proof of real RP support. |
| Conformance / certification signal | **IV** — 7-check harness is implemented/tested and now emits explicit scope labels (`reference-stub` / `real-runtime-untrusted` / `real-runtime-certified`) | **DO** — only stub/fake runtime validated in-repo; real runtime remains an external check | **IA** — consumer can use report output without over-reading stub passes as product certification | Valuable tool, and now safer to interpret because scope is explicit. |
| RepoPrompt plugin / MCP consumer of projection | **Gap** — no code in this repo implements such a consumer | **Gap** — no shared runtime/plugin contract beyond general docs | **Gap** — no in-repo plugin, MCP bridge, or end-to-end consumer test | Largest consumer-side integration hole. |
| External-project consumption of compiled RP output | **IV** — producer side is stable and documented | **DO** — runtime requirements depend on manual vs auto usage | **DO** — docs explain usage, but no example repo or integration test exists | Adoption path is described, not demonstrated. |

## Current decision posture

| Layer | Posture | Interpretation |
| --- | --- | --- |
| **aiwf core** | Strong | RP integration logic, contract persistence, compile surfaces, and manual workflow are largely in place. |
| **RP runtime/provider** | Weak | Most runtime capabilities are specified or stub-modeled, not validated against a real RepoPrompt binary. |
| **RepoPrompt/plugin/project-consumer** | Partial | aiwf emits stable surfaces, but there is almost no proof of real consumer uptake beyond human manual handoff. |

**Key takeaway:** the main constraint is no longer basic aiwf-side modeling. The limiting factors are (a) lack of real RP runtime validation and (b) lack of a real consumer/plugin that reads the emitted RP surfaces.

## Prioritized recommendations

### A. Work executable in this repo now

| Priority | Recommendation | Why now |
| --- | --- | --- |
| **A1** | Extend `conformance rp` to cover exit-code semantics and `metadata` round-trip. | These are already specified, partially modeled, and low-cost to validate in-repo. |
| **A2** | Add `partial` response coverage to the reference stub and conformance suite. | `aiwf` already handles `partial`; the stub/conformance gap is now the weak link. |
| **A3** | Use `docs/RP_REAL_RUNTIME_VALIDATION.md` when validating `/usr/local/bin/rp-cli` on an operator machine. | The runbook now makes the stub-vs-product boundary explicit and actionable. |
| **A4** | Treat `scope=reference-stub` as repo-only confidence and require explicit operator promotion for `real-runtime-certified`. | Conformance output is now labeled; the remaining work is disciplined operator use of those labels. |
| **A5** | Consider surfacing a machine-readable RP protocol readiness signal in projection output. | Projection consumers currently see protocol version, but not clear readiness posture. |

### B. Cross-repo coordination dependencies

| Priority | Recommendation | Dependency | Why it matters |
| --- | --- | --- | --- |
| **C1** | Run `aiwf conformance rp` against the real RepoPrompt app / MCP CLI runtime. | Access to the real RP binary | This is the fastest path to turning Layer 2 from documented-only into validated reality. |
| **C2** | Define and implement a RepoPrompt-side plugin or MCP consumer for `rp-projection.json`. | RepoPrompt/plugin engineering | This is the missing proof that aiwf’s stable emitted surfaces are actually consumable by RepoPrompt-native automation. |
| **C3** | Create an example external project that compiles and consumes `.rp/compiled/`. | Cross-repo sample/template ownership | This would validate install-surface and projection contracts from the consumer side. |
| **C4** | Align future CI/release checks with a pinned real-runtime validation path once available. | RP runtime release/distribution coordination | Without this, CI will remain a stub-confidence signal rather than a product-confidence signal. |

## Decision rule for next steps

- If the goal is **higher confidence without external coordination**, do **A1–A4**.
- If the goal is **actual RP integration proof**, prioritize **C1** first.
- If the goal is **RepoPrompt-native automation**, prioritize **C2** after or alongside **C1**.
