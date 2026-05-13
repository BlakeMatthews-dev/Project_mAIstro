---
id: S-022
title: "Bouncer — security screening (20+ regex + LLM)"
domain: security
status: done
priority: P1
effort: ""
created: 2026-02-25
completed: 2026-03-23
owner: conductor
commits: [259bf0b]
---

# S-022: Bouncer

Pre-execution security screen: 20+ regex patterns for injection/exfil/prompt-attack patterns, negative LLM pass for ambiguous cases. Blocks non-recoverable `TOOL_VIOLATION` and `SAFETY_VIOLATION` errors.

## Key files
- `conductor/orchestrator/agents/bouncer.py`

## warden.file_scan()

File attachments entering conductor via any channel (email, MCP, A2A) pass through a multi-stage analysis pipeline before their content touches any agent context. The pipeline's only job is routing content to Warden with the correct trust label — Warden makes all judgment calls. The only hard blocks at the file-analysis layer are structural integrity failures (magic bytes mismatch) and resource-exhaustion risks (zip bombs).

### Stage 1: Magic bytes vs. declared extension

Read the first 16 bytes of the file. Compare against a map of known magic-byte signatures (PDF `%PDF-`, ZIP `PK\x03\x04`, PNG `\x89PNG`, JPEG `\xFF\xD8\xFF`, etc.).

- **Match**: proceed to Stage 2.
- **Mismatch**: **hard block** — log `FILE_INTEGRITY_VIOLATION`, reject the file. A PNG that starts with `PK\x03\x04` is a ZIP being disguised; no further analysis needed.

### Stage 2: Hidden ZIP scan

Scan the entire file for the ZIP local-file header magic bytes (`PK\x03\x04`) at any byte offset beyond the expected location (i.e., not at offset 0 for a declared ZIP).

- **Not found**: proceed to Stage 3.
- **Found at unexpected offset**: extract the embedded archive, recurse through Stage 1–5 for each entry, and label the entire file and its contents **untrusted** → Warden scan. Do not hard block — the outer file may legitimately contain a ZIP payload (e.g., DOCX/XLSX are ZIPs); the trust label is what matters.

### Stage 3: File size mismatch

For compressed or archive formats, compare declared uncompressed size to the actual size on disk.

- **Extreme compression ratio** (uncompressed > 1 GB or ratio > 1000:1): **hard block** — log `ZIP_BOMB_DETECTED`. This is a resource-exhaustion risk, not just a content concern.
- **Excess bytes** (file on disk is materially larger than expected based on declared size/format): label the file **untrusted** → Warden scan.

### Stage 4: strings extraction

Run the equivalent of `strings -n 4` on the raw binary to extract all printable ASCII/UTF-8 sequences of 4 or more characters.

- **Non-text-carrier file type** (e.g., PNG, JPEG, BMP, WAV): the format carries no intentional text payload. Any extracted strings — including metadata fields — are labeled **untrusted** → Warden scan.
- **Text-carrier file type** (e.g., PDF, HTML, DOCX, plain text): expected to contain text. Proceed to Stage 5.

### Stage 5: Parser vs. strings diff (text-carrier only)

Parse the file with its native parser (PDF renderer, HTML parser, DOCX extractor) to extract the human-visible text content. Diff this against the strings output from Stage 4.

- **Strings output is a subset of parser output** (no new strings): content is consistent — pass the parsed text to Warden with a **standard trust label**.
- **Strings output contains content not in parser output**: the diff — strings that appear in the raw binary but not in the parsed document — may be hidden instructions, steganographic payload, or polyglot content. Label the diff content **untrusted** → Warden scan. The parsed text is still labeled standard.

### Trust label routing summary

| Condition | Label | Action |
|---|---|---|
| Magic bytes mismatch | — | Hard block (`FILE_INTEGRITY_VIOLATION`) |
| Zip bomb | — | Hard block (`ZIP_BOMB_DETECTED`) |
| Clean file (all stages pass) | standard | Warden scan (standard path) |
| Hidden ZIP detected | untrusted | Warden scan (elevated scrutiny) |
| File size excess bytes | untrusted | Warden scan (elevated scrutiny) |
| Non-text-carrier strings | untrusted | Warden scan (elevated scrutiny) |
| Parser vs. strings diff | untrusted | Warden scan (elevated scrutiny) |

Warden applies its full injection/exfil/prompt-attack pattern set to all content regardless of trust label. The trust label controls whether Warden's LLM pass runs in permissive or strict mode, and whether a human review flag is added to the audit record.

### Key files
- `conductor/orchestrator/agents/warden_file_scan.py` (new)
- `conductor/orchestrator/agents/bouncer.py` (wire `file_scan()` into attachment handling)
