from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.session import Base
from app.modules.creation.infrastructure.models import (
    NovelCreationImportChunk,
    NovelCreationMaterialImport,
    NovelCreationSession,
)
from app.services.novel_creation_imports import (
    apply_material_import,
    build_import_preview,
    deterministic_extract_chunk,
    mark_interrupted_material_imports,
    parse_creation_material,
    split_creation_material,
)
from app.services import novel_creation_imports as import_service
from app.services.novel_creation_workspace import initialize_session_draft, save_stage, serialize_creation_artifact


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _session(db) -> NovelCreationSession:
    session = NovelCreationSession(status="drafting", user_brief="导入现有大纲")
    db.add(session)
    initialize_session_draft(session, {"preset_id": "free", "target_chapters": 160})
    db.flush()
    return session


def _import(db, session: NovelCreationSession, *, status: str = "waiting_user") -> NovelCreationMaterialImport:
    raw = b"material"
    run = NovelCreationMaterialImport(
        session_id=session.id,
        filename="outline.md",
        stored_path=str(Path("outline.md")),
        media_type="md",
        file_sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        status=status,
        input_revision=int(session.revision or 0),
    )
    db.add(run)
    db.flush()
    return run


def test_parse_supports_markdown_and_json_and_chunks_long_text():
    markdown, extension = parse_creation_material("outline.md", "# 第一卷\n内容".encode())
    assert extension == "md"
    assert "第一卷" in markdown
    payload, extension = parse_creation_material("outline.json", json.dumps({"characters": [{"name": "林七"}]}, ensure_ascii=False).encode())
    assert extension == "json"
    assert "林七" in payload
    chunks = split_creation_material(("段落资料\n" * 3000).strip())
    assert len(chunks) >= 2
    assert chunks[1][0] < chunks[0][1]


def test_deterministic_extraction_preserves_source_provenance():
    db = _db()
    session = _session(db)
    run = _import(db, session)
    extracted = deterministic_extract_chunk(
        "# 人物设定\n- 林七：失忆医师\n- 周渡：隔离站长\n\n第一卷 封城\n进入灰港",
        run,
        3,
    )
    assert [row["name"] for row in extracted["characters"]] == ["林七", "周渡"]
    assert extracted["characters"][0]["_source"] == {
        "source_file_id": run.id,
        "source_chunk": 3,
        "source_message_id": None,
        "import_run_id": run.id,
        "confidence": 0.72,
    }
    assert extracted["volumes"][0]["title"] == "第一卷 封城"


def test_preview_counts_candidates_and_reports_existing_conflict():
    db = _db()
    session = _session(db)
    save_stage(session, "characters", {"characters": [{"name": "旧主角", "role_type": "protagonist", "goal": "守城"}], "relationships": []})
    run = _import(db, session)
    chunk = NovelCreationImportChunk(
        import_run_id=run.id, chunk_index=0, char_start=0, char_end=10,
        content_hash="a" * 64, text="人物", status="completed", confidence=90,
        extraction_json={"characters": [{"name": "林七", "goal": "寻母", "_source": {"source_chunk": 0, "confidence": .9}}]},
    )
    db.add(chunk)
    db.flush()
    preview = build_import_preview(run, session)
    assert preview["detected"]["characters"] == 1
    assert {row.get("artifact") for row in preview["conflicts"]} == {"characters"}


def test_apply_selected_artifacts_is_revision_guarded_and_keeps_provenance():
    db = _db()
    session = _session(db)
    run = _import(db, session)
    run.preview_json = {
        "artifact_counts": {"characters": 1},
        "candidates": {
            "characters": [{"name": "林七", "goal": "寻母", "role_type": "protagonist", "_source": {"source_chunk": 0, "confidence": .91}}],
            "locations": [], "factions": [], "worldbuilding": [], "volumes": [], "chapters": [], "notes": [],
        },
    }
    revision = int(session.revision or 0)
    with pytest.raises(RuntimeError, match="revision_conflict"):
        apply_material_import(db, run, selected_artifacts=["characters"], strategy="merge", expected_revision=revision + 1)
    assert serialize_creation_artifact(session, "characters")["data"] is None
    result = apply_material_import(db, run, selected_artifacts=["characters"], strategy="merge", expected_revision=revision)
    artifact = serialize_creation_artifact(session, "characters")
    assert result["applied"] == [{"artifact": "characters", "count": 1}]
    assert artifact["data"]["characters"][0]["name"] == "林七"
    assert artifact["data"]["_import_provenance"]["source_file_id"] == run.id
    assert run.status == "completed"


def test_confirmed_and_locked_artifacts_are_not_overwritten():
    db = _db()
    session = _session(db)
    save_stage(session, "characters", {"characters": [{"name": "作者主角", "role_type": "protagonist", "goal": "守城"}], "relationships": []}, confirm=True)
    draft = dict(session.draft_json)
    draft["artifact_locks"] = {"characters": ["/characters/0"]}
    session.draft_json = draft
    run = _import(db, session)
    run.preview_json = {
        "artifact_counts": {"characters": 1},
        "candidates": {"characters": [{"name": "模型主角", "goal": "离城", "_source": {"source_chunk": 0, "confidence": .8}}]},
    }
    result = apply_material_import(db, run, selected_artifacts=["characters"], strategy="overwrite_unconfirmed", expected_revision=int(session.revision or 0))
    assert result["applied"] == []
    assert result["skipped"] == [{"artifact": "characters", "reason": "locked_fields"}]
    assert serialize_creation_artifact(session, "characters")["data"]["characters"][0]["name"] == "作者主角"


def test_startup_marks_active_import_interrupted_but_keeps_chunks():
    db = _db()
    session = _session(db)
    run = _import(db, session, status="running")
    db.add(NovelCreationImportChunk(
        import_run_id=run.id, chunk_index=0, char_start=0, char_end=2,
        content_hash="b" * 64, text="资料", status="completed", confidence=72,
    ))
    assert mark_interrupted_material_imports(db) == 1
    assert run.status == "interrupted"
    assert run.chunks[0].status == "completed"


def test_background_import_persists_each_chunk_and_builds_preview(tmp_path, monkeypatch):
    database_path = tmp_path / "imports.db"
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        session = _session(db)
        db.commit()
        source = tmp_path / "long-outline.md"
        source.write_text(("# 人物设定\n- 林七：失忆医师\n\n第一卷 封城\n进入灰港\n" * 2000), encoding="utf-8")
        raw = source.read_bytes()
        run = NovelCreationMaterialImport(
            session_id=session.id,
            filename=source.name,
            stored_path=str(source),
            media_type="md",
            file_sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
            status="queued",
            input_revision=int(session.revision or 0),
        )
        db.add(run)
        db.commit()
        import_id = run.id
    monkeypatch.setattr(import_service, "SessionLocal", factory)
    asyncio.run(import_service.run_material_import(import_id))
    with factory() as db:
        persisted = db.get(NovelCreationMaterialImport, import_id)
        assert persisted.status == "waiting_user"
        assert persisted.chunk_count > 1
        assert persisted.processed_chunks == persisted.chunk_count
        assert all(chunk.status == "completed" for chunk in persisted.chunks)
        assert persisted.checkpoint_json == {"phase": "preview_ready", "next_chunk": persisted.chunk_count}
        assert persisted.preview_json["detected"]["characters"] >= 1


def test_same_session_and_file_replays_one_durable_import(tmp_path, monkeypatch):
    db = _db()
    session = _session(db)
    monkeypatch.setattr(import_service, "content_root", lambda: tmp_path)
    raw = "# 八卷大纲\n第一卷 起势".encode("utf-8")
    first, replayed = import_service.create_material_import(
        db, session, filename="大纲.md", raw=raw,
    )
    assert replayed is False
    db.flush()
    second, replayed = import_service.create_material_import(
        db, session, filename="重复提交.md", raw=raw,
    )
    assert replayed is True
    assert second.id == first.id
    assert db.query(NovelCreationMaterialImport).count() == 1
