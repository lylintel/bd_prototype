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