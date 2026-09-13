"""Build complete v4 plans around explicit domain-write fixtures.

Domain projection tests supply short records; this adds the required planning
metadata and selects their exact fixture IDs, without involving a provider.
"""
import json
from uuid import uuid4

from app.database.models import CatalogingCandidate, Character, WorldbuildingEntry
from app.services.cataloging.candidate_io import candidate_payload
from app.services.cataloging.applier import apply_candidates_for_run
from tests.test_cataloging_plan import plan_rows


def complete_fixture_plan(db, job, run):
    db.flush()
    rows = db.query(CatalogingCandidate).filter_by(chapter_run_id=run.id).filter(
        CatalogingCandidate.status != "rejected").all()
    bindings = {"character": {}, "worldbuilding": {}}
    for row in rows:
        payload = candidate_payload(row)
        if row.item_type == "chapter_link" and "character_names" in payload:
            payload["characters"] = [{"name": name, "appearance_type": "出场"} for name in payload.pop("character_names")]
        if row.item_type.startswith("character_") and row.item_type not in {"character_relationship", "character_merge_candidate"}:
            name = payload.get("name")
            identity = payload.get("id") or row.target_id
            entity = db.get(Character, identity) if identity else db.query(Character).filter_by(project_id=job.project_id, name=name).first()
            if entity:
                name, identity = entity.name, entity.id
                payload["id"] = identity
                if row.item_type == "character_create":
                    row.item_type = "character_update"
                    payload.pop("client_id", None)
                decision = "existing"
            else:
                identity = payload.get("client_id") or bindings["character"].get(name, {}).get("id") or str(uuid4())
                payload["client_id" if row.item_type == "character_create" else "id"] = identity
                decision = "new"
            if name:
                bindings["character"][name] = {"name": name, "id": identity, "decision": decision, "reason": "Explicit test character"}
        elif row.item_type.startswith("worldbuilding_"):
            name = payload.get("title")
            identity = payload.get("id") or row.target_id
            entity = db.get(WorldbuildingEntry, identity) if identity else db.query(WorldbuildingEntry).filter_by(project_id=job.project_id, title=name, status="active").first()
            if entity and entity.status == "active":
                identity, name = entity.id, entity.title
                payload["id"] = identity
                if row.item_type == "worldbuilding_create":
                    row.item_type = "worldbuilding_update"
                    payload.pop("client_id", None)
                decision = "existing"
            else:
                identity = payload.get("client_id") or bindings["worldbuilding"].get(name, {}).get("id") or str(uuid4())
                payload["client_id" if row.item_type == "worldbuilding_create" else "id"] = identity
                decision = "new"
            if name:
                bindings["worldbuilding"][name] = {"name": name, "id": identity, "decision": decision, "reason": "Explicit test setting"}
        row.raw_payload = json.dumps(payload, ensure_ascii=False)
    for kind, model, key in (("character", Character, "name"), ("worldbuilding", WorldbuildingEntry, "title")):
        # Links in fixtures explicitly cite exact names of pre-seeded records.
        for row in rows:
            payload = candidate_payload(row)
            names = [item.get("name") for item in payload.get("characters", []) if isinstance(item, dict)] if kind == "character" else payload.get("worldbuilding_titles", [])
            if kind == "character":
                names += [payload[field] for field in ("source_name", "target_name", "primary_name", "secondary_name") if field in payload]
            for name in names:
                entity = db.query(model).filter(model.project_id == job.project_id, getattr(model, key) == name).first()
                if entity and name not in bindings[kind]:
                    bindings[kind][name] = {"name": name, "id": entity.id, "decision": "existing", "reason": "Explicit linked fixture"}
    defaults = plan_rows()
    summary = next((row for row in rows if row.item_type == "chapter_summary"), None)
    if summary is None:
        summary = CatalogingCandidate(job_id=job.id, chapter_run_id=run.id, project_id=job.project_id,
            chapter_id=run.chapter_id, item_type="chapter_summary", raw_payload=json.dumps(defaults[0]), sort_order=-1)
        db.add(summary)
        rows.append(summary)
    payload = candidate_payload(summary)
    default_manifest = dict(defaults[0]["coverage_manifest"])
    scene_numbers = [candidate_payload(row).get("scene_number", 0) for row in rows if row.item_type in {"outline_create", "outline_update"}]
    default_manifest["scene_count"] = max([1, *scene_numbers])
    manifest = payload.setdefault("coverage_manifest", default_manifest)
    for key, value in defaults[0]["coverage_manifest"].items():
        manifest.setdefault(key, value)
    payload.setdefault("scenes", ["Fixture scene"] * manifest["scene_count"])
    payload.setdefault("narrative_state", {})
    payload.setdefault("narrative_review", {"source": "provided", "outcome": "assessed"})
    payload["character_bindings"] = list(bindings["character"].values())
    payload["worldbuilding_bindings"] = list(bindings["worldbuilding"].values())
    summary.raw_payload = json.dumps(payload, ensure_ascii=False)
    if not any(row.item_type in {"outline_create", "outline_update"} and candidate_payload(row).get("node_type") == "chapter" for row in rows):
        outline = {**defaults[1], "title": run.chapter.title}
        db.add(CatalogingCandidate(job_id=job.id, chapter_run_id=run.id, project_id=job.project_id,
            chapter_id=run.chapter_id, item_type="outline_create", raw_payload=json.dumps(outline), sort_order=1))
    db.flush()


def apply_fixture_plan(db, job, run):
    complete_fixture_plan(db, job, run)
    events = apply_candidates_for_run(db, job, run)
    assert all(event["type"] == "candidate_applied" for event in events), [event.get("error") for event in events]
    return events
