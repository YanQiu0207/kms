# Agent Board

| Agent | Scope | Owned Paths | Status | Notes |
|---|---|---|---|---|
| Main | Coordination, integration, review, final fixes | repo-wide | Active | Enforces stage gate |
| Worker A | M0 runtime scaffold | `pyproject.toml`, `README.md`, `app/main.py`, `app/config.py`, `app/schemas.py`, `app/__init__.py` | Complete | M0 merged by main agent |
| Worker B | M0 package skeleton | `app/ingest/**`, `app/store/**`, `app/retrieve/**`, `app/answer/**`, `app/adapters/**`, `tests/**` | Complete | M0 merged by main agent |
| Worker C | M1 ingest pipeline | `app/ingest/loader.py`, `app/ingest/markdown_parser.py`, `app/ingest/chunker.py`, `app/ingest/state.py` | Complete | M1 merged and reviewed by main agent |
| Worker D | M1 store pipeline | `app/store/sqlite_store.py`, `app/store/fts_store.py`, `app/store/vector_store.py` | Complete | M1 merged and reviewed by main agent |
| Worker E | M2 retrieval pipeline | `app/retrieve/lexical.py`, `app/retrieve/semantic.py`, `app/retrieve/hybrid.py`, `app/retrieve/rerank.py` | 已实现待审 | 词法/语义/RRF/rerank 已完成，等主 agent 接线 |
| Worker F | M3 answer pipeline | `app/answer/prompt.py`, `app/answer/guardrail.py`, `app/answer/citation_check.py` | Dispatched | Awaiting result |

## Rules

- Workers own only the paths assigned here.
- Workers must not revert unrelated changes.
- Main agent reviews every completed stage before advancing.
