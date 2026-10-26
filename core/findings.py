"""Shared structure for plan-health and SHIELD findings.

`source` is always shown to the user so they can tell what is known from what is guessed:
  USER_REPORTED - the user entered or answered it; LESEDI cannot confirm it is true or complete.
  INFERRED      - LESEDI derived it from the user's settings; it may be wrong.
  SYSTEM_CHECKED- LESEDI checked a fact it holds itself (for example, a date or a recorded confirmation).
  None of these verify a person's real-world trustworthiness or detect spyware."""
from dataclasses import dataclass

USER_REPORTED = "user_reported"
INFERRED = "inferred"
SYSTEM_CHECKED = "system_checked"

SOURCE_LABELS = {
    USER_REPORTED: "You told us",
    INFERRED: "Suggested from your settings",
    SYSTEM_CHECKED: "Checked by the system",
}

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True)
class Finding:
    code: str
    title: str
    why: str
    action: str
    severity: str  # "high" | "medium" | "low"
    source: str

    @property
    def source_label(self):
        return SOURCE_LABELS[self.source]


def sort_findings(findings):
    return sorted(findings, key=lambda f: (SEVERITY_ORDER[f.severity], f.code))
