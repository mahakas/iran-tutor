# Release Readiness (Phase 7 audit)

Branch: `arena/67538167-iran-tutor` (base `c0497ca`, Phase 6 merged).
Scope: security audit, hardening of the findings below, configuration parity, and
verification. Product features are unchanged.

## 1. Verification results

| Check | Result |
|---|---|
| `pytest -q` (backend, full) | 293 passed, 1 skipped |
| Phase 7 targeted tests (`tests/test_phase7_hardening.py`) | 10 passed |
| `alembic upgrade head` (fresh DB) | OK, head `c3d4e5f6a7b8` |
| `alembic check` | Drift only in column *types* (`JSONB`→`JSON` on SQLite dialect) across `exam_sessions`, `book_pages`, `chat_sessions`, `flashcard_decks`, `flashcard_reviews`. No missing tables or columns. Accepted as dialect noise; no migration added. |
| `tsc --noEmit` | Clean (exit 0) |
| `npm run build` | Passed |

## 2. Findings and actions

### Fixed in this phase

1. **Upload content not verified** (`services/upload_guard.py`, new).
   - Personal file upload (`api/account.py`) checked only the extension. It now verifies the
     magic bytes and rejects text-type files that contain binary.
   - Chat audio (`api/tutor.py`) trusted the client `Content-Type`. It now verifies the bytes
     against the declared MIME type.
   - Admin book upload (`api/admin.py`) now checks the `%PDF-` header and uses a
     server-chosen stored suffix instead of the client filename suffix.
2. **Persian search mismatch** (`services/search_normalize.py`, new).
   Arabic `ي`/`ك`/`ة` and ZWNJ were normalized only in RAG lexical search. Chat search
   (Python-side) and curriculum search (SQL `ilike`) now use the same folding, so
   `كتاب` matches `کتاب`.
3. **Provider probe not audited** (`services/ai_gateway.py`). Every admin connectivity
   probe (`probe_endpoint`) now writes an `ai_audit_logs` row with `feature_key=provider_probe`
   and `flag_reason=provider_probe`. The row stores the base URL, status, and outcome. It never
   stores the key or the raw upstream body.
4. **Weak admin default is silent** (`app/main.py`). Startup logs a warning when
   `ADMIN_PASSWORD` is still a known-weak value. Startup is not blocked, so local development keeps working.
5. **Incomplete configuration template.** `.env.example` now lists every required and optional
   setting. Each key was checked against `Settings` fields.

### Reviewed and accepted (no change)

- **IDOR candidates** (all verified scoped):
  `deep_solve_service.get_owned` (user check), `notebook_service` (`_owned_notebook`,
  `_owned_block` scoped to `notebook_id`), `flashcard_sources` (`user_id` check on chat and exam),
  `mistake_bank_service._owned`, account storage (`user_id` plus `status=active`),
  `api/kb.py` `/figures/{id}/image` (router-level `require_admin`).
  `chat_stream` and `immersive_service` take IDs from the owner-checked route or only read public
  book metadata.
- **Feedback flag on unowned audit rows:** an existing test
  (`test_student_can_flag_an_ai_answer_into_admin_queue`) deliberately lets a student flag
  an unowned audit row. A tighter owner check was tried and reverted because it breaks
  that product rule. **Residual risk, low:** a student who knows an unowned audit ID can add a flag.
  Flagging adds only a queue entry; it reads and modifies no data. Revisit if audit IDs become guessable.
- **LLM connectivity test error path:** `probe_endpoint` already scrubs the key from every
  error string (`_scrub`). No extra redaction was needed.
- **Admin error details** (`str(exc)`, lines 340, 437, 1164, 1645, 1915, 2092) carry operator-side
  validation text, not secrets. The SMS test path already redacts.
- **Curriculum search** returns only `status=ready` books and pages (textbook content meant for students).
- **Content serving:** HTML is served as `text/plain` unless downloaded, and `nosniff` is set.
- **Capabilities:** `api/exams.py` enforces `check_capability_access(... "quiz")`. The
  account, curriculum, and kb routers have none. Account and curriculum are not AI-backed;
  kb is admin-only.
- **AI-call governance:** SDK and HTTP calls for AI live only in `core/llm_client.py`. Only
  `ai_gateway.py` imports it. The `probe_endpoint` exception is now audited (item 3).
- **Frontend XSS:** `dangerouslySetInnerHTML` appears only in `SvgDiagram` and `MermaidDiagram`.
  SVG is sanitized with DOMPurify plus an allowlist before insertion, and not during SSR.
  Mermaid runs with `securityLevel: "strict"` after `isSafeMermaidSource`. No `rehype-raw` or `eval`.
- **Secrets in responses:** provider serializers return `api_key: None`. `system/status` is non-secret.
  No `NEXT_PUBLIC_*` usage and no console logging in frontend code.
- **Desktop or bot code:** none in product code. The Electron and Tauri matches are transitive lockfile entries.
  `backend/scripts/*.py` are operator tools, not user-facing.

### Open items for the next phase

- `ADMIN_PASSWORD` default `"123"` remains the code default. Operators must set a real value;
  the startup warning is the only guard.
- Per-capability quota is still missing (carried from Phase 5).
- Text-to-book grounding check outside Living Book is still missing (carried from Phase 5).
- `alembic check` type drift on five tables. A Postgres-based check is needed to confirm whether it is dialect-only.
- Feedback flag on unowned audit rows (accepted residual risk above).

## 3. Configuration

- `docker-compose.yml` binds Postgres, Qdrant, and Redis to `127.0.0.1` only. Required values use
  `${VAR:?...}`. The API itself is not in Compose and runs from `backend/`.
- `.env.example` documents the LLM, admin, secret, SMS, payment, and Qdrant settings.
  Real secrets must go in `.env` and must never be committed.
