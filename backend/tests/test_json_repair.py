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


def test_parser_ignores_reasoning_blocks_and_uses_the_final_json_object():
    raw = '<think>先比较 {"draft": true}，再输出最终结构。</think>\n说明如下：\n```json\n{"data":{"characters":[{"name":"周遥"}]}}\n```'

    parsed, method = parse_json_object_detailed(raw)

    assert parsed == {"data": {"characters": [{"name": "周遥"}]}}
    assert method == "direct"


def test_parser_prefers_the_largest_valid_payload_when_prose_contains_braces():
    raw = '调试片段 {"ok":true}\n最终答案：{"data":{"title":"主方案","items":[1,2,3]}}'

    parsed, method = parse_json_object_detailed(raw)

    assert parsed == {"data": {"title": "主方案", "items": [1, 2, 3]}}
    assert method == "direct"
