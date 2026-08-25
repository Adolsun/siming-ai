# Novel Creation Cross-Codebase Consistency Audit

> Date: 2026-06-09
> Auditor: Claude Code

> The checklist below is retained as the original audit. The current cataloging
> closure audit is recorded here on 2026-08-12 and supersedes any old workflow
> descriptions.

## 2026-08-12 Cataloging closure audit

### One write path

Chapter creation, body edits, rewrites, and version restores all launch
`services/cataloging/launcher.py`. A model cannot disable this with an
`auto_cataloging` argument. The removed post-write side-channel tools are not
registered, exposed over MCP, or allowed to reappear in prompts/source by
`test_no_legacy_post_write_archive.py`.

| Execution route | Extraction | Same acceptance gate | Same applier | Post-write verification |
|---|---|---:|---:|---:|
| Internal API/model | fact inventory, then candidate resolution | ✅ | ✅ | ✅ |
| Managed local CLI | canonical external prompt and JSONL candidates | ✅ | ✅ | ✅ |
| External MCP agent | canonical external prompt and JSONL candidates | ✅ | ✅ | ✅ |

The public seed contains metadata only. Its runtime prompt, workflow, forbidden
patterns, version and hash are compiled from
`prompt_specs/continuity/cataloging-external.md`; the former inline two-stage
prompt has been deleted.

### Generation, persistence, and consumption matrix

| Archive data | Generation contract | Persistence rule | Consumers checked |
|---|---|---|---|
| Chapter summary | non-empty summary plus five-part `coverage_manifest` | singleton candidate can be repaired by a later retry; never shadowed by an earlier empty candidate | chapter list/detail, adjacent-summary context, external writing context |
| Chapter/section outline | one chapter node and 2–6 sections when the text has multiple scenes | sections resolve `parent_title` to the chapter node; chapter links use real IDs | outline UI, target outline context, chapter ordering |
| Character identity/card | create/update carries aliases, base biography, abilities, stable `profile`, and voice configuration | new characters require a meaningful profile candidate; no relationship/state candidate may manufacture a blank character | character editor, snapshots, RAG index, internal writing, role-play, API/CLI/external writing |
| Character current state | every declared character has an identity-matched state update | all current-state fields update independently from the stable card | cataloging context, writing context, character UI |
| Character relationships | exact source, target, and relationship type in both fact inventory and coverage manifest | both endpoint cards must already exist; exact candidate identity is required | relation graph, targeted cataloging context, all writing context routes |
| Worldbuilding | exact manifest titles and matching create/update/timeline cards | role-like concepts cannot be written as characters | worldbuilding UI, RAG, cataloging and writing contexts |
| Chapter links | declared characters/worldbuilding must be linked to the chapter | identities are checked, duplicate cards cannot satisfy counts | chapter detail, outline/character selection, context retrieval |
| Narrative governance | complete narrative state and explicit review, including stable resolution identity | incomplete or guessed resolutions remain reviewable instead of silently closing | governance page, task context, exact source locator |

`services/character_archive.py` is the canonical read model for character data.
It projects base fields, current state, the ten stable profile fields, aliases,
AI voice settings, and relationships. Character/relationship/alias/voice edits
invalidate prepared writing manifests so stale data cannot be reused.

### UI closure

- “定位原文” stores the evidence and source version, opens the source chapter,
  finds the strongest exact/normalized excerpt, focuses the editor, and selects
  that range. A changed version or missing excerpt is reported instead of
  pretending that the source was found.
- Automatic cataloging operations are projected into project-assistant chat as
  durable start, wait, success, failure, cancellation, and interruption
  messages. The start message warns that immediately writing the next chapter
  may use incomplete context; only a completed validated operation says it is
  safe to continue.

### Regression fences

The focused suites cover source-fact reverse validation, exact relationship
identity, stable profile evidence, no blank relationship endpoints, complete
character round trips, API/CLI parity, automatic launch, old-tool removal,
prompt single ownership, chat notifications, and exact editor selection.

## Audit Checklist

### 1. New Tools Registered Once in ToolRegistry

**Status: PASS**

All new tools are registered in `backend/app/services/workspace/registry.py`:

| Tool | Registry | Internal Agent | Scheduler | MCP | Frontend Catalog |
|------|----------|---------------|-----------|-----|-----------------|
| `prepare_external_writing_context` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `save_external_chapter_draft` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `get_external_chapter_draft` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `record_external_quality_review` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `create_chapter` / `update_chapter` automatic cataloging launch | ✅ | ✅ | ✅ | ✅ | ✅ |
| `list_prompt_packs` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `get_prompt_pack` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `get_tool_playbook` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `get_quality_rubric` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `start_novel_creation_session` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `draft_novel_blueprint` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `review_novel_blueprint` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `apply_novel_blueprint` | ✅ | ✅ | ✅ | ✅ | ✅ |

Verification: `py scripts/check-tool-registry.py` — PASS, 119 tools.

### 2. Tool Schemas Consistent

**Status: PASS**

All tool schemas are defined in the `ToolDef.input_schema` field in `registry.py`. The MCP adapter reads these directly. Frontend tool catalog derives from the same registry.

No manual schema lists maintained separately.

### 3. Long-Content Workflows Use draft_id/content_ref

**Status: PASS**

- `save_external_chapter_draft` returns `draft_id`/`content_ref`
- `create_chapter` accepts `draft_id` to avoid passing full text through tool arguments
- `record_external_quality_review` accepts `draft_id` or `chapter_id`
- Chapter content is stored server-side, not copied through repeated calls

### 4. Prompt Packs Match Between Internal and External

**Status: PASS**

- `inject_public_prompt_pack_section()` appends the same public pack data to internal prompts
- External agents fetch packs via `get_prompt_pack` which reads from the same `PublicPromptPack` table
- Version matching: internal prompt builder records pack version, external agents receive pack version

### 5. Runtime Schema Sync

**Status: PASS**

New tables added:
- `public_prompt_packs` — prompt pack storage
- `method_cards` — method card storage
- `novel_creation_sessions` — creation session tracking

All use `Base` from `app.database.session` which supports runtime schema sync via `ensure_runtime_schema()`.

### 6. Old Projects Compatible

**Status: PASS**

- No existing tables modified
- No existing columns changed
- New tables are additive-only
- Runtime schema sync creates missing tables on startup

### 7. Permission Packs Correct

**Status: PASS**

| Tool | Pack | Reason |
|------|------|--------|
| `prepare_external_writing_context` | readonly_collaboration | API-free read |
| `save_external_chapter_draft` | readonly_collaboration | API-free storage |
| `get_external_chapter_draft` | readonly_collaboration | API-free read |
| `record_external_quality_review` | readonly_collaboration | API-free storage |
| `list_prompt_packs` | readonly_collaboration | API-free read |
| `get_prompt_pack` | readonly_collaboration | API-free read |
| `get_tool_playbook` | readonly_collaboration | API-free read |
| `get_quality_rubric` | readonly_collaboration | API-free read |
| `start_novel_creation_session` | readonly_collaboration | API-free |
| `draft_novel_blueprint` | readonly_collaboration | API-free |
| `review_novel_blueprint` | readonly_collaboration | API-free |
| `create_chapter` / `update_chapter` | project_writing | Writes the chapter and creates a canonical single-chapter cataloging job |
| `apply_novel_blueprint` | project_management | Creates project |

Verification: No API key/model secret tools exposed in any pack.

### 8. Frontend Pages Follow Conventions

**Status: PASS**

- `PromptPacksPage.tsx` — uses Ant Design Card/Collapse/Tag patterns
- `ExternalWritingPanel.tsx` — uses Ant Design Card/Collapse/Button patterns
- `NovelCreationWizardPage.tsx` — uses Ant Design Steps/Form patterns
- `ExternalAgentRunPanel.tsx` — uses Ant Design Collapse/Badge/Tag patterns
- `ExternalAgentPermissionPanel.tsx` — uses Ant Design Card/Switch/Alert patterns

All follow existing Siming UI conventions.

### 9. Documentation Consistent

**Status: PASS**

- `docs/agent/shared-prompt-pack-contract.md` — uses "Prompt Pack", "Method Card", "permission pack"
- `docs/agent/external-no-api-writing.md` — uses "external agent", "API-free"
- `docs/agent/novel-project-creation-task-board.md` — consistent terminology
- `docs/mcp/claude-code-codex-client.md` — updated with "No Siming API mode"
- `README.md` — updated with external agent writing reference

### 10. Tests Cover Both Modes

**Status: PASS**

- Internal API-backed mode: `test_prompt_packs.py`, `test_quality_mode_shared_prompts.py`
- External no-API mode: `test_external_writing_no_api_e2e.py`, `test_external_writing_context.py`
- Novel creation: `test_novel_creation_brief.py`, `test_novel_blueprint_draft.py`, `test_apply_novel_blueprint.py`
- MCP exposure: `test_mcp_prompt_pack_tools.py`, `test_mcp_external_writing_tools.py`, `test_mcp_novel_creation_tools.py`

## Summary

All 10 audit checks pass. The implementation is consistent across backend, frontend, MCP, prompts, tools, tests, and docs.
