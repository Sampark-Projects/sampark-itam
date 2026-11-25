"""Asset tag / naming standard.

A rule has a pattern made of literal text and tokens:

    {SEQ:4}  running number, zero-padded to at least 4 digits (counter kept on the rule)
    {SITE}   code of the asset site
    {YYYY}   four-digit year      {YY}  two-digit year

Example: "DEW-{SITE}-PLC-{SEQ:4}" -> "DEW-P1-PLC-0007".

The functions here are pure (no database) so they are easy to test.
"""
from app.services.local_time import local_today
import re
from datetime import date
from typing import Optional

TOKEN_RE = re.compile(r"\{(SEQ(?::(\d{1,2}))?|SITE|YYYY|YY)\}")
ANY_BRACE_RE = re.compile(r"[{}]")
MAX_PATTERN_LENGTH = 100
# characters allowed in a generated tag: what a person can type on a label or in a tag field
SAFE_LITERAL_RE = re.compile(r"^[A-Za-z0-9._/\-\s]*$")


class PatternError(ValueError):
    pass


def _split(pattern: str):
    """Yield ('lit', text) and ('tok', match) parts, rejecting stray braces."""
    pos = 0
    for m in TOKEN_RE.finditer(pattern):
        if m.start() > pos:
            yield "lit", pattern[pos:m.start()]
        yield "tok", m
        pos = m.end()
    if pos < len(pattern):
        yield "lit", pattern[pos:]


def check_pattern(pattern: str) -> str:
    """Return the cleaned pattern or raise PatternError."""
    pattern = (pattern or "").strip()
    if not pattern:
        raise PatternError("pattern is empty")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise PatternError(f"pattern is longer than {MAX_PATTERN_LENGTH} characters")
    seq_count = 0
    for kind, part in _split(pattern):
        if kind == "lit":
            if ANY_BRACE_RE.search(part):
                raise PatternError("unknown or unfinished token")
            if not SAFE_LITERAL_RE.match(part):
                raise PatternError("literal text may only use letters, digits and . _ / - and spaces")
        elif part.group(1).startswith("SEQ"):
            seq_count += 1
            width = part.group(2)
            if width is not None and not (1 <= int(width) <= 10):
                raise PatternError("{SEQ:n} needs n between 1 and 10")
    if seq_count != 1:
        raise PatternError("the pattern needs exactly one {SEQ} token so that tags are unique")
    return pattern


def _seq_width(match) -> int:
    return int(match.group(2)) if match.group(2) else 1


def render(pattern: str, seq: int, site_code: Optional[str] = None, today: Optional[date] = None) -> str:
    """Build a tag from a pattern for the given counter value."""
    today = today or local_today()
    out = []
    for kind, part in _split(pattern):
        if kind == "lit":
            out.append(part)
            continue
        token = part.group(1)
        if token.startswith("SEQ"):
            out.append(str(seq).zfill(_seq_width(part)))
        elif token == "SITE":
            out.append((site_code or "").strip())
        elif token == "YYYY":
            out.append(f"{today.year:04d}")
        elif token == "YY":
            out.append(f"{today.year % 100:02d}")
    return "".join(out)


def to_regex(pattern: str, site_code: Optional[str] = None) -> "re.Pattern[str]":
    """Regex that accepts every tag the pattern can produce."""
    out = []
    for kind, part in _split(pattern):
        if kind == "lit":
            out.append(re.escape(part))
            continue
        token = part.group(1)
        if token.startswith("SEQ"):
            out.append(r"\d{%d,}" % _seq_width(part))
        elif token == "SITE":
            out.append(re.escape((site_code or "").strip()))
        elif token == "YYYY":
            out.append(r"\d{4}")
        elif token == "YY":
            out.append(r"\d{2}")
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE)


def matches(pattern: str, tag: str, site_code: Optional[str] = None) -> bool:
    return bool(to_regex(pattern, site_code).match(tag or ""))


def example(pattern: str, site_code: Optional[str] = None) -> str:
    return render(pattern, 1, site_code)
