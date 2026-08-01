from app.core.json_repair import parse_json_object, parse_json_object_detailed


def test_deterministic_json_repair_handles_fences_punctuation_and_trailing_commas():
    parsed, method = parse_json_object_detailed('```json\n说明：{“角色”:[{"name":"周遥",}],}\n```')

    assert parsed == {"角色": [{"name": "周遥"}]}
    assert method == "deterministic_json"


def test_deterministic_json_repair_closes_a_truncated_object():
    raw = '{"data":{"characters":[{"name":"周遥","goal":"查明真相"}]'

    parsed, method = parse_json_object_detailed(raw)

    assert parsed == {"data": {"characters": [{"name": "周遥", "goal": "查明真相"}]}}
    assert method == "deterministic_json"
    assert parse_json_object(raw) == parsed
