# rp-cli-stub (internal reference test harness)

Internal reference `rp-cli` stub for validating `aiwf-rp-native/v1` process integration.

> This tool is for local/CI protocol testing only. It is **not** a production RepoPrompt runtime and must not be used as evidence that `aiwf` is ready for the real RepoPrompt app / MCP CLI runtime.

## Install

```bash
pip install ./tools/rp-cli-stub
```

## Usage

### Protocol probe

```bash
rp-cli-stub --aiwf-protocol-version
```

### Envelope mode

```bash
echo '{"protocol":"aiwf-rp-native","version":1,"request_type":"plan","stage":"plan","prompt":"hello","context":{},"options":{},"metadata":{}}' | rp-cli-stub
```

### Legacy raw stdin fallback

```bash
echo 'legacy input' | rp-cli-stub
```

### Forced protocol error (for conformance tests)

```bash
echo '{"protocol":"aiwf-rp-native","version":1,"request_type":"execute","stage":"implement","prompt":"x"}' | rp-cli-stub --force-error PROMPT_TOO_LARGE
```

When `--force-error UNSUPPORTED_VERSION` is used, the error detail includes `supported_version: 1`.
