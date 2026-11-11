from pathlib import Path

import yaml


def test_ci_workflow_is_valid_yaml_with_string_commands():
    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
    document = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert {"push", "pull_request"} <= document["on"].keys()
    for job in document["jobs"].values():
        for step in job["steps"]:
            if "run" in step:
                assert isinstance(step["run"], str)


def test_browser_checks_use_a_supported_pinned_linux_image():
    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
    document = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert document["jobs"]["checks"]["runs-on"] == "ubuntu-24.04"
    assert document["jobs"]["pyslang-spike"]["strategy"]["matrix"]["os"] == ["ubuntu-latest", "windows-latest"]