# Archived Project Handover

This file is retained only as a historical development snapshot. Its dated notes,
test counts, implementation details and earlier security descriptions may no
longer match the current application.

For the current project description, architecture, setup instructions, AI
integration, privacy boundaries, limitations and evaluator links, use the
[README](README.md). The README and the current source code are the authoritative
references for judging and technical review.

- [Live application](https://arthasheild.vercel.app/)
- [Demo video](https://youtu.be/oXG0cLqUp08)
- [Public source repository](https://github.com/fjprojects/Arthasheild)

ArthaShield processes statements on its Django backend. Its optional Gemini
integration receives sanitized information only after server-side redaction
and residual-pattern checks. This is a heuristic privacy boundary, not a
zero-knowledge system or a legal-compliance certification. Financial figures
and decision verdicts are produced by deterministic Python logic.
