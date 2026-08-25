from app.services.character_role_types import (
    append_character_role_description,
    character_role_description,
    normalize_character_role_type,
)


def test_model_prose_role_is_reduced_to_protagonist() -> None:
    assert normalize_character_role_type("主角，穿越者，陆家三岁孙女") == "protagonist"
    assert character_role_description("主角，穿越者，陆家三岁孙女") == "穿越者、陆家三岁孙女"
    assert append_character_role_description(
        "前世是研究员。",
        "主角，穿越者，陆家三岁孙女",
    ) == "前世是研究员。\n\n身份补充：穿越者、陆家三岁孙女"


def test_relationship_to_protagonist_does_not_become_protagonist() -> None:
    assert normalize_character_role_type("主角的父亲") == "supporting"


def test_internal_merged_alias_sentinel_is_preserved() -> None:
    assert normalize_character_role_type("merged_alias") == "merged_alias"


def test_unknown_model_role_falls_back_to_canonical_other() -> None:
    assert normalize_character_role_type("穿越者，阵法研究者") == "other"
