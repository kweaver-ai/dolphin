import json

from dolphin.lib.skillkits.env_skillkit import EnvSkillkit


class _DummyExecutor:
    env_type = "local"
    working_dir = "/tmp/test-working-dir"

    def is_connected(self) -> bool:
        return True


def test_get_env_info_accepts_props_and_returns_json():
    skillkit = EnvSkillkit(executor=_DummyExecutor())

    result = skillkit._get_env_info(props={"gvp": object()})
    payload = json.loads(result)

    assert payload["type"] == "local"
    assert payload["connected"] is True
    assert payload["working_dir"] == "/tmp/test-working-dir"
