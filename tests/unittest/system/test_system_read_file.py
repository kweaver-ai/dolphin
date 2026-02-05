import pytest

from dolphin.lib.skillkits.system_skillkit import SystemFunctionsSkillKit


def test_read_file_replaces_invalid_utf8(tmp_path):
    skillkit = SystemFunctionsSkillKit()

    file_path = tmp_path / "invalid_utf8.txt"
    file_path.write_bytes(b"ok\xff\xfeend")

    content = skillkit._read_file(str(file_path))
    assert content.startswith("[WARNING] File is not valid UTF-8; decoded with replacement characters.\n")
    assert "ok" in content
    assert "\ufffd" in content
    assert "end" in content


def test_read_file_valid_utf8_no_warning(tmp_path):
    skillkit = SystemFunctionsSkillKit()

    file_path = tmp_path / "utf8.txt"
    file_path.write_text("hello世界", encoding="utf-8")

    content = skillkit._read_file(str(file_path))
    assert not content.startswith("[WARNING] ")
    assert content == "hello世界"


def test_read_file_missing_path_raises_runtime_error(tmp_path):
    skillkit = SystemFunctionsSkillKit()

    missing_path = tmp_path / "missing.txt"
    with pytest.raises(RuntimeError):
        skillkit._read_file(str(missing_path))

def test_read_file_normalizes_path_formats(tmp_path, monkeypatch):
    skillkit = SystemFunctionsSkillKit()

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ALFRED_TEST_DIR", str(tmp_path))

    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")

    assert skillkit._read_file(" `~/a.txt` " ) == "hello"
    assert skillkit._read_file("'~/a.txt'") == "hello"
    assert skillkit._read_file('\"~/a.txt\"') == "hello"
    assert skillkit._read_file(" $ALFRED_TEST_DIR/a.txt " ) == "hello"

