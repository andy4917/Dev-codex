from __future__ import annotations


PRIVATE_KEY_MARKERS = (
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "-----END OPENSSH PRIVATE KEY-----",
    "-----BEGIN PRIVATE KEY-----",
    "-----END PRIVATE KEY-----",
)


def redact_private_key_text(text: str) -> str:
    redacted = str(text)
    for marker in PRIVATE_KEY_MARKERS:
        redacted = redacted.replace(marker, "[REDACTED PRIVATE KEY MARKER]")
    return redacted

