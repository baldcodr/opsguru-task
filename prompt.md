Build a small retrieval-augmented Q&A agent that answers natural-language questions about CloudNova's invoices and accounts.

Ingest + chunk + embed the data into a vector store (Chroma, FAISS, LanceDB, pgvector — your call; local is fine).
A question-answering interface: CLI or a thin API endpoint (POST /ask). No frontend required.
Answers must cite which rows/records they came from.
It should handle at least a few of the stakeholder questions in BUSINESS_CONTEXT.md — including ones that require applying business rules (e.g. only paid invoices count as revenue), not just semantic lookup. Tell us honestly where pure RAG struggles with the aggregation-style questions.
Use a framework if you like (LangChain, LlamaIndex, DSPy) or roll it by hand — justify the choice in the README.



Either track should be runnable from a single command after setup (python -m app, etc.).


What we actually care about (the rubric)
You are scored on these, roughly in priority order:

Spec-Driven Development. Did you write the spec first and drive the AI from it? We want to see the spec as an artifact, not reverse-engineered after the fact.
How you used AI. We read your .claude/ (or equivalent) config and prompt history. Good prompting, good context-setting, and good judgment about when to override the AI all score highly.
Evaluation & honesty about limits. A small eval harness with a handful of question→expected-answer cases beats a demo that only works on the happy path. Tell us the failure modes.
Production instincts. Error handling, config over hardcoding, secrets not committed, sane project structure, a diagram that matches the code.
Communication. The README should let a customer stakeholder understand what you built and why in 3 minutes.

Required deliverables — a GitHub repo containing:
A submission missing items 1–5 is considered incomplete. Item 6 is a differentiator.

README.md with:

What it does and how to run it (setup + the single demo command).
The spec you wrote (inline or linked in /specs).
Key design decisions and trade-offs, and what you'd do with another day.
Known limitations and failure modes (be honest — this scores higher than pretending there are none).

.claude/ directory (or CLAUDE.md, .cursorrules, copilot-instructions.md — whatever your tool uses) showing how you configured and steered the AI. This is a first-class artifact for this role, not an afterthought. If your tool keeps a prompt/session log, include a trimmed version under /docs.

A system architecture diagram committed to the repo (/docs/architecture.*). An .excalidraw, Mermaid-in-README, PNG, or draw.io export are all fine. It must reflect what you actually built — data flow from raw input → processing → store → query/answer.

/specs — the spec(s) that drove the build (schema spec, eval spec, API contract — whatever applies to your track).

An eval harness (/evals or tests/) — a runnable script with a small set of cases and a way to see pass/fail. Even 5 cases is enough; seed them from the stakeholder questions in BUSINESS_CONTEXT.md. Include one case you expect to fail and say why.

(Bonus) One "production hardening" touch — e.g. a Dockerfile, a CI check (GitHub Action running the evals), input validation/guardrails, caching, or a cost/latency measurement. Pick one; don't gold-plate.
