# rp-cli-stub

Reference standalone `rp-cli` stub for validating `aiwf-rp-native/v1` process integration.

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
