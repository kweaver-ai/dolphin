import pytest

from dolphin.lib.skillkits.system_skillkit import SystemFunctionsSkillKit


def test_read_file_replaces_invalid_utf8(tmp_path):
    skillkit = SystemFunctionsSkillKit()

    file_path = tmp_path / "invalid_utf8.txt"
    file_path.write_bytes(b"ok\xff\xfeend")

    content = skillkit._read_file(str(file_path))
    assert "ok" in content
    assert "end" in content


def test_read_file_missing_path_raises_runtime_error(tmp_path):
    skillkit = SystemFunctionsSkillKit()

    missing_path = tmp_path / "missing.txt"
    with pytest.raises(RuntimeError):
        skillkit._read_file(str(missing_path))
