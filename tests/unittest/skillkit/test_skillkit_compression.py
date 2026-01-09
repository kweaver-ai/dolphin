import json
import unittest


from dolphin.core.skill.skillkit import Skillkit


class TestSkillkitCompression(unittest.TestCase):
    def test_include_rule_keeps_only_specified_fields(self):
        message = 'prefix =>#my_skill:{"a":1, "b":2, "c":3} suffix'
        rules = {"my_skill": {"include": ["b"]}}
        compressed = Skillkit.compress_message_with_rules(message, rules)

        # 提取压缩后的 JSON 以验证内容
        start = compressed.find("=>#my_skill:")
        self.assertNotEqual(start, -1)
        payload_start = compressed.find("{", start)
        payload_end = compressed.find("}", payload_start)
        data = json.loads(compressed[payload_start : payload_end + 1])

        self.assertEqual(set(data.keys()), {"b"})
        self.assertEqual(data["b"], 2)

    def test_exclude_rule_drops_specified_fields(self):
        message = '=>#my_skill:{"keep": "yes", "drop": "no", "also": 1}'
        rules = {"my_skill": {"exclude": ["drop"]}}
        compressed = Skillkit.compress_message_with_rules(message, rules)

        start = compressed.find("=>#my_skill:")
        payload_start = compressed.find("{", start)
        payload_end = compressed.find("}", payload_start)
        data = json.loads(compressed[payload_start : payload_end + 1])

        self.assertIn("keep", data)
        self.assertIn("also", data)
        self.assertNotIn("drop", data)

    def test_multiple_markers_are_all_processed(self):
        message = 'head =>#skillA:{"x": 1, "y": 2} mid =>#skillB:{"u": 3, "v": 4} tail'
        rules = {
            "skillA": {"include": ["y"]},
            "skillB": {"exclude": ["v"]},
        }
        compressed = Skillkit.compress_message_with_rules(message, rules)

        # 校验 skillA
        start_a = compressed.find("=>#skillA:")
        self.assertNotEqual(start_a, -1)
        a_start = compressed.find("{", start_a)
        a_end = compressed.find("}", a_start)
        data_a = json.loads(compressed[a_start : a_end + 1])
        self.assertEqual(set(data_a.keys()), {"y"})
        self.assertEqual(data_a["y"], 2)

        # 校验 skillB
        start_b = compressed.find("=>#skillB:")
        self.assertNotEqual(start_b, -1)
        b_start = compressed.find("{", start_b)
        b_end = compressed.find("}", b_start)
        data_b = json.loads(compressed[b_start : b_end + 1])
        self.assertIn("u", data_b)
        self.assertNotIn("v", data_b)

    def test_no_matching_rules_keeps_original(self):
        message = '=>#unknown:{"a":1, "b":2}'
        compressed = Skillkit.compress_message_with_rules(message, rules={})
        self.assertEqual(message, compressed)


if __name__ == "__main__":
    unittest.main()
