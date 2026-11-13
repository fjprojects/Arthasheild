"""
Controlled parsing errors for financial ingestion.

A parser error can be triggered by arbitrary user content (a malformed row, an
undecodable byte, a corrupted document). Such an error must never quote the
content that caused it, so the ingestion pipeline raises this dedicated type
with a content-free message. It derives from ``ValueError`` so existing
``except ValueError`` handlers keep working.
"""


class StatementParseError(ValueError):
    """A controlled, content-free statement parsing error."""
