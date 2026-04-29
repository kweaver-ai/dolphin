"""Unit tests for dolphin.sdk.skill.skill_contracts.

Covers:
- Contract name constants have expected, stable values
- Description strings are non-empty and mention the relevant contract
- Input schemas satisfy minimal JSON Schema requirements
- Output schemas declare all fields mandated by the design
- build_openai_tool_schema() produces the correct OpenAI function-calling layout
- Pre-built SKILL_*_OPENAI_SCHEMA constants are correctly wired
"""

import unittest


class TestContractNameConstants(unittest.TestCase):
    """Contract names must be fixed strings that the executor and SDK share."""

    def setUp(self):
        from dolphin.sdk.skill.skill_contracts import (
            BUILTIN_SKILL_LOAD,
            BUILTIN_SKILL_READ_FILE,
            BUILTIN_SKILL_EXECUTE_SCRIPT,
        )
        self.LOAD = BUILTIN_SKILL_LOAD
        self.READ = BUILTIN_SKILL_READ_FILE
        self.EXEC = BUILTIN_SKILL_EXECUTE_SCRIPT

    def test_load_name(self):
        self.assertEqual(self.LOAD, "builtin_skill_load")

    def test_read_file_name(self):
        self.assertEqual(self.READ, "builtin_skill_read_file")

    def test_execute_script_name(self):
        self.assertEqual(self.EXEC, "builtin_skill_execute_script")

    def test_names_are_unique(self):
        names = {self.LOAD, self.READ, self.EXEC}
        self.assertEqual(len(names), 3, "Contract names must be distinct")

    def test_names_are_strings(self):
        for name in (self.LOAD, self.READ, self.EXEC):
            self.assertIsInstance(name, str)


class TestContractDescriptions(unittest.TestCase):
    """Descriptions must be non-empty strings containing key guidance."""

    def setUp(self):
        from dolphin.sdk.skill.skill_contracts import (
            SKILL_LOAD_DESCRIPTION,
            SKILL_READ_FILE_DESCRIPTION,
            SKILL_EXECUTE_SCRIPT_DESCRIPTION,
        )
        self.desc_load = SKILL_LOAD_DESCRIPTION
        self.desc_read = SKILL_READ_FILE_DESCRIPTION
        self.desc_exec = SKILL_EXECUTE_SCRIPT_DESCRIPTION

    def test_descriptions_are_non_empty_strings(self):
        for desc in (self.desc_load, self.desc_read, self.desc_exec):
            self.assertIsInstance(desc, str)
            self.assertGreater(len(desc.strip()), 20)

    def test_load_description_mentions_phase_1(self):
        """Load description must guide model to call it first."""
        lower = self.desc_load.lower()
        self.assertTrue(
            "phase 1" in lower or "first" in lower or "must be called first" in lower,
            "Load description should indicate it must be called first",
        )

    def test_read_description_mentions_optional(self):
        lower = self.desc_read.lower()
        self.assertIn("optional", lower)

    def test_exec_description_mentions_optional(self):
        lower = self.desc_exec.lower()
        self.assertIn("optional", lower)


class TestContractInputSchemas(unittest.TestCase):
    """Input schemas must satisfy minimal JSON Schema requirements."""

    def setUp(self):
        from dolphin.sdk.skill.skill_contracts import (
            SKILL_LOAD_INPUTS_SCHEMA,
            SKILL_READ_FILE_INPUTS_SCHEMA,
            SKILL_EXECUTE_SCRIPT_INPUTS_SCHEMA,
        )
        self.load_schema = SKILL_LOAD_INPUTS_SCHEMA
        self.read_schema = SKILL_READ_FILE_INPUTS_SCHEMA
        self.exec_schema = SKILL_EXECUTE_SCRIPT_INPUTS_SCHEMA

    def _assert_valid_schema(self, schema, expected_required):
        self.assertIsInstance(schema, dict)
        self.assertEqual(schema.get("type"), "object")
        props = schema.get("properties", {})
        self.assertIsInstance(props, dict)
        required = schema.get("required", [])
        for field in expected_required:
            self.assertIn(field, props, f"Missing property: {field}")
            self.assertIn(field, required, f"Not in required: {field}")

    def test_load_requires_skill_id(self):
        self._assert_valid_schema(self.load_schema, ["skill_id"])

    def test_read_file_requires_skill_id_and_file_path(self):
        self._assert_valid_schema(self.read_schema, ["skill_id", "file_path"])

    def test_execute_script_requires_skill_id_and_script_path(self):
        self._assert_valid_schema(self.exec_schema, ["skill_id", "entry_shell"])

    def test_all_property_types_are_strings(self):
        for schema in (self.load_schema, self.read_schema, self.exec_schema):
            for prop_name, prop_def in schema["properties"].items():
                self.assertEqual(
                    prop_def.get("type"),
                    "string",
                    f"Property '{prop_name}' type should be 'string'",
                )

    def test_property_descriptions_are_non_empty(self):
        for schema in (self.load_schema, self.read_schema, self.exec_schema):
            for prop_name, prop_def in schema["properties"].items():
                self.assertIn(
                    "description",
                    prop_def,
                    f"Property '{prop_name}' is missing a description",
                )
                self.assertTrue(
                    prop_def["description"].strip(),
                    f"Property '{prop_name}' has an empty description",
                )


class TestContractOutputSchemas(unittest.TestCase):
    """Output schemas must declare all fields from the design contract."""

    def setUp(self):
        from dolphin.sdk.skill.skill_contracts import (
            SKILL_LOAD_OUTPUTS,
            SKILL_READ_FILE_OUTPUTS,
            SKILL_EXECUTE_SCRIPT_OUTPUTS,
        )
        self.load_out = SKILL_LOAD_OUTPUTS
        self.read_out = SKILL_READ_FILE_OUTPUTS
        self.exec_out = SKILL_EXECUTE_SCRIPT_OUTPUTS

    def test_load_outputs_fields(self):
        for field in ("skill_id", "skill_md_content", "available_scripts",
                      "available_references", "source"):
            self.assertIn(field, self.load_out, f"load outputs missing: {field}")

    def test_read_file_outputs_fields(self):
        for field in ("skill_id", "file_path", "content", "source"):
            self.assertIn(field, self.read_out, f"read_file outputs missing: {field}")

    def test_execute_script_outputs_fields(self):
        for field in ("skill_id", "entry_shell", "stdout", "stderr",
                      "exit_code", "duration_ms", "artifacts", "source"):
            self.assertIn(field, self.exec_out, f"execute_script outputs missing: {field}")


class TestBuildOpenaiToolSchema(unittest.TestCase):
    """build_openai_tool_schema must produce the OpenAI function-calling format."""

    def setUp(self):
        from dolphin.sdk.skill.skill_contracts import build_openai_tool_schema
        self.build = build_openai_tool_schema

    def test_output_structure(self):
        schema = self.build(
            name="test_func",
            description="A test function.",
            inputs_schema={"type": "object", "properties": {}, "required": []},
        )
        self.assertEqual(schema["type"], "function")
        func = schema["function"]
        self.assertEqual(func["name"], "test_func")
        self.assertEqual(func["description"], "A test function.")
        self.assertIn("parameters", func)

    def test_parameters_are_forwarded_verbatim(self):
        params = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
        schema = self.build("f", "d", params)
        self.assertEqual(schema["function"]["parameters"], params)

    def test_function_name_preserved(self):
        schema = self.build("builtin_skill_load", "desc", {"type": "object", "properties": {}})
        self.assertEqual(schema["function"]["name"], "builtin_skill_load")


class TestPreBuiltOpenAISchemas(unittest.TestCase):
    """Pre-built SKILL_*_OPENAI_SCHEMA constants must reference the correct contract names."""

    def setUp(self):
        from dolphin.sdk.skill.skill_contracts import (
            BUILTIN_SKILL_LOAD,
            BUILTIN_SKILL_READ_FILE,
            BUILTIN_SKILL_EXECUTE_SCRIPT,
            SKILL_LOAD_OPENAI_SCHEMA,
            SKILL_READ_FILE_OPENAI_SCHEMA,
            SKILL_EXECUTE_SCRIPT_OPENAI_SCHEMA,
        )
        self.LOAD = BUILTIN_SKILL_LOAD
        self.READ = BUILTIN_SKILL_READ_FILE
        self.EXEC = BUILTIN_SKILL_EXECUTE_SCRIPT
        self.load_schema = SKILL_LOAD_OPENAI_SCHEMA
        self.read_schema = SKILL_READ_FILE_OPENAI_SCHEMA
        self.exec_schema = SKILL_EXECUTE_SCRIPT_OPENAI_SCHEMA

    def test_load_schema_name_matches_constant(self):
        self.assertEqual(self.load_schema["function"]["name"], self.LOAD)

    def test_read_schema_name_matches_constant(self):
        self.assertEqual(self.read_schema["function"]["name"], self.READ)

    def test_exec_schema_name_matches_constant(self):
        self.assertEqual(self.exec_schema["function"]["name"], self.EXEC)

    def test_all_schemas_have_type_function(self):
        for s in (self.load_schema, self.read_schema, self.exec_schema):
            self.assertEqual(s["type"], "function")

    def test_all_schemas_have_non_empty_description(self):
        for s in (self.load_schema, self.read_schema, self.exec_schema):
            self.assertTrue(s["function"]["description"].strip())

    def test_load_schema_has_skill_id_parameter(self):
        params = self.load_schema["function"]["parameters"]
        self.assertIn("skill_id", params["properties"])

    def test_read_schema_has_file_path_parameter(self):
        params = self.read_schema["function"]["parameters"]
        self.assertIn("file_path", params["properties"])

    def test_exec_schema_has_script_path_parameter(self):
        params = self.exec_schema["function"]["parameters"]
        self.assertIn("entry_shell", params["properties"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
