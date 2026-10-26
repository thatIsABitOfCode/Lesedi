"""Best-effort screening of text that will be seen by other people.

This catches only OBVIOUS personal details and calls to violence. It cannot recognise a name, a nickname, a car
registration or a description that points at one person, and it cannot judge whether something is defamatory.
Moderator review is the real control; this only stops the easiest mistakes. It never echoes the matched text."""
import re

_PATTERNS = [
    ("a phone number or ID number", re.compile(r"(?:\d[\s().\-]*){9,}")),
    ("an email address", re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")),
    ("a web link", re.compile(r"https?://|www\.", re.IGNORECASE)),
    ("a street address or house number", re.compile(
        r"\b\d{1,5}\s+(?:[a-z']+\s+){0,3}(?:street|st|road|rd|avenue|ave|drive|dr|lane|ln|crescent|cres|close|way"
        r"|boulevard|blvd)\b", re.IGNORECASE)),
    ("a stand, erf or unit number", re.compile(r"\b(?:erf|stand|unit|flat|house)\s*(?:no\.?|number|#)?\s*\d+",
                                              re.IGNORECASE)),
    ("a call to harm or hunt someone", re.compile(
        r"\b(?:let'?s|we should|we must|go and|someone should)\s+(?:all\s+)?(?:kill|burn|beat|hang|lynch|attack|hunt"
        r"|find)\b", re.IGNORECASE)),
]


def screen_text(text: str) -> list[str]:
    """Return short descriptions of what was found, e.g. ["an email address"]. Empty list means nothing obvious."""
    found = []
    for label, pattern in _PATTERNS:
        if pattern.search(text or "") and label not in found:
            found.append(label)
    return found
