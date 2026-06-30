import json
import re
import tarfile
from collections import Counter, defaultdict
from pathlib import Path

from fastapi.testclient import TestClient

from codesetarena.constants import (
    AI_REVIEWER_STUDENT_NUMBER,
    AUTHOR_TESTS_PER_PROBLEM,
    DISPLAY_VERSION,
    EXECUTION_PYTHON_IMAGE,
    EXECUTION_TARGET_SECONDS,
    EXECUTION_TIMEOUT_SECONDS,
    EXECUTION_PYTHON_VERSION,
    KIND_PROBLEMS,
    KIND_REVIEWS,
    KIND_REVISION,
    PROBLEMS_PER_STUDENT,
    PROMPT_TEMPLATE_ID,
    PUBLIC_TESTS_PER_PROBLEM,
    ROLE_STUDENT,
    ROLE_TEACHER,
    STAGE1,
    STAGE2,
    STAGE3,
)
from codesetarena.form_limits import FORM_LIMITS
from codesetarena.package_names import student_package_name, teacher_package_name
from codesetarena.packages import read_package, write_package
from codesetarena.paths import ensure_student_tree, ensure_teacher_tree
from codesetarena.prompting import render_official_prompt
from codesetarena.storage import load_student_state
from codesetarena.storage import save_student_state
from codesetarena.storage import load_teacher_state
from codesetarena.storage import save_teacher_state
from codesetarena.student_app import create_student_app
from codesetarena.teacher_app import create_teacher_app


def test_student_and_teacher_headers_show_display_version(tmp_path):
    student_client = TestClient(create_student_app(tmp_path / "student"))
    teacher_client = TestClient(create_teacher_app(tmp_path / "teacher"))

    student_page = student_client.get("/stage1")
    teacher_page = teacher_client.get("/stage1")

    assert f"<title>CodeSetArena 学生端 {DISPLAY_VERSION}</title>" in student_page.text
    assert f"<title>CodeSetArena 助教端 {DISPLAY_VERSION}</title>" in teacher_page.text
    assert student_page.text.count(f'class="version-badge">{DISPLAY_VERSION}</span>') == 1
    assert teacher_page.text.count(f'class="version-badge">{DISPLAY_VERSION}</span>') == 1


def test_student_stage1_export_and_directory_isolation(tmp_path):
    student_root = tmp_path / "student"
    teacher_root = tmp_path / "teacher"
    ensure_student_tree(student_root)
    ensure_teacher_tree(teacher_root)
    assert (student_root / "stage1-original").exists()
    assert (teacher_root / "stage1-submissions").exists()
    assert not (student_root / "stage1-submissions").exists()
    assert not (teacher_root / "stage1-original").exists()

    client = TestClient(create_student_app(student_root))
    client.post("/student-info", data={"student_number": "2026000001", "name": "Alice", "class_id": "A"})
    for _ in range(PROBLEMS_PER_STUDENT + 1):
        _create_valid_selected_problem(client, student_root)
    response = client.post("/stage1/package", follow_redirects=False)
    assert response.status_code == 303
    assert f"必须选择 {PROBLEMS_PER_STUDENT} 道有效题目进行打包" in client.get(response.headers["location"]).text
    _select_stage1_problem_package(client, student_root)
    response = client.post("/stage1/package", follow_redirects=False)
    assert response.status_code == 303
    filename = response.headers["location"].split("download=", 1)[1]
    assert filename == "2026000001-student-stage1-problems.tar.gz"
    download = client.get(f"/downloads/{filename}")
    assert download.status_code == 200

    manifest, payload = read_package(student_root / "stage1-original/exports" / filename)
    assert manifest["package_role"] == ROLE_STUDENT
    assert manifest["package_stage"] == STAGE1
    assert manifest["package_kind"] == KIND_PROBLEMS
    assert payload["student"]["student_number"] == "2026000001"
    assert len(payload["problems"]) == PROBLEMS_PER_STUDENT
    assert all(len(problem["run_records"]) == 1 for problem in payload["problems"])
    assert all(problem["run_records"][0]["package_selected"] for problem in payload["problems"])


def test_student_stage1_list_detail_and_run_results(tmp_path, monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-student-env-secret")
    student_root = tmp_path / "student"
    client = TestClient(create_student_app(student_root))
    client.post(
        "/settings",
        data={
            "student_number": "2026000001",
            "name": "Alice",
            "class_id": "A",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-student-secret",
            "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
        },
    )
    response = client.post("/stage1/problems", follow_redirects=False)
    assert response.status_code == 303
    detail_path = response.headers["location"].split("?", 1)[0]

    home = client.get("/stage1")
    assert "题目列表" in home.text
    assert "Public tests，每行一条 JSON" not in home.text
    assert "<th>测试</th>" not in home.text
    assert "最近结果" not in home.text
    assert "<th>已选运行</th>" in home.text
    assert "<th>题目状态</th>" in home.text
    assert "保存打包题目选择" not in home.text
    assert "data-stage1-selection-form" in home.text
    assert detail_path in home.text

    detail = client.get(detail_path)
    assert "执行运行" in detail.text
    assert "返回题目列表" in detail.text
    assert "保存与校验" in detail.text
    assert "样例数据" in detail.text
    assert "测试数据" in detail.text
    assert 'name="public_kwargs_0"' in detail.text
    assert 'name="public_expected_0"' in detail.text
    assert 'name="author_kwargs_4"' in detail.text
    assert 'name="author_expected_4"' in detail.text
    assert 'name="statement" rows="16"' in detail.text
    assert 'name="reference_solution" rows="20"' in detail.text
    assert "格式正确" in detail.text
    assert "写清楚要解决的问题" in detail.text
    assert "点击“保存题目并校验参考答案”会保存当前题目" in detail.text
    assert "这里列出当前题目的模型作答记录" in detail.text
    assert "当前 v7 本地运行使用参考答案作为 mock 提取代码" not in detail.text
    assert "API_KEY</th>" not in detail.text
    assert "Authorization 仅保存脱敏标记" not in detail.text
    assert "fetch(action" in detail.text
    assert "window.scrollTo(window.scrollX, scrollY)" in detail.text
    assert 'path.endsWith("/validate")' in detail.text
    assert 'path.endsWith("/run")' in detail.text
    assert 'path.endsWith("/runs/package-selection")' in detail.text
    assert 'path.endsWith("/delete")' in detail.text
    assert "EXACT_MATCH" not in detail.text
    assert "题目状态" in detail.text
    assert "problem-progress-panel" in detail.text
    assert 'role="progressbar"' in detail.text
    assert 'aria-valuemax="3"' in detail.text
    assert 'aria-valuenow="1"' in detail.text
    assert "草稿已创建" in detail.text
    assert "参考答案校验" in detail.text
    assert "运行记录已选择" in detail.text
    assert "请先保存题目并校验参考答案" in detail.text
    assert "<span>运行记录</span>" not in detail.text
    assert "<span>合法运行</span>" not in detail.text
    assert "<span>不 pass</span>" not in detail.text
    assert "<span>参考答案失败</span>" not in detail.text
    assert detail.text.find("<h2>说明</h2>") > detail.text.find("<h3>模型运行记录</h3>")
    assert "完整提示词" not in detail.text
    assert "模型提示词" in detail.text
    assert '<pre class="prompt-preview" id="prompt-preview"' in detail.text
    assert '<textarea class="prompt-preview"' not in detail.text

    valid_problem_data = _valid_problem_data()

    response = client.post(
        f"{detail_path}/run",
        data=valid_problem_data,
        follow_redirects=False,
    )
    assert response.status_code == 303
    detail = client.get(response.headers["location"])
    assert "请先点击“保存题目并校验参考答案”完成校验" in detail.text
    assert load_student_state(student_root)["problems"][0]["run_records"] == []

    response = client.post(
        f"{detail_path}/validate",
        data=valid_problem_data,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "#validation-panel" in response.headers["location"]
    detail = client.get(response.headers["location"])
    assert "“保存题目并校验参考答案”会执行参考答案和 7 个测试用例" in detail.text
    validation_panel_start = detail.text.find('id="validation-panel"')
    validation_panel_end = detail.text.find("参考答案执行结果", validation_panel_start)
    validation_panel = detail.text[validation_panel_start:validation_panel_end]
    assert validation_panel.find("“保存题目并校验参考答案”会执行参考答案和 7 个测试用例") < validation_panel.find(
        "保存题目并校验参考答案</button>"
    )
    assert validation_panel.find("保存题目并校验参考答案</button>") < validation_panel.find("校验通过")
    assert 'id="validation-status" data-valid="true"' in validation_panel
    assert '<span class="status-pill ok">校验通过</span>' in validation_panel
    assert "题目已经校验通过" not in detail.text
    assert "参考答案执行结果" in detail.text
    assert detail.text.find("参考答案执行结果") > detail.text.find("保存与校验")
    assert detail.text.find("参考答案执行结果") < detail.text.find("模型执行运行")
    assert "校验结果" not in detail.text
    assert "样例数据" in detail.text
    assert "测试数据" in detail.text
    assert "模型提示词" in detail.text
    assert "temperature=0.0" in detail.text
    assert "top_p=1.0" in detail.text
    assert f"请根据题目实现下面的 Python {EXECUTION_PYTHON_VERSION} 函数" in detail.text
    assert EXECUTION_PYTHON_IMAGE in detail.text
    assert f"尽量在 {EXECUTION_TARGET_SECONDS:g} 秒内完成" in detail.text
    assert f"{EXECUTION_TIMEOUT_SECONDS:g} 秒超时阈值" in detail.text
    assert "不鼓励用超时制造难点" in detail.text
    assert "输出要求" in detail.text
    assert "只输出完整函数定义" in detail.text
    assert "回答中不能出现三个反引号" not in detail.text
    assert "示例 p-0" not in detail.text
    assert "输入 kwargs=" not in detail.text
    assert "输入：{&#34;x&#34;:1}；输出：1。" in detail.text
    assert 'prompt-part problem' in detail.text
    assert 'prompt-part template' in detail.text
    assert '<pre class="prompt-preview" id="prompt-preview"' in detail.text
    assert '<textarea class="prompt-preview"' not in detail.text
    state = load_student_state(student_root)
    assert state["problems"][0]["validation"]["status"] == "passed"
    assert len(state["problems"][0]["validation"]["test_results"]) == 7

    response = client.post(
        f"{detail_path}/run",
        data=valid_problem_data,
        follow_redirects=False,
    )
    assert response.status_code == 303
    detail = client.get(response.headers["location"])
    assert "执行模型运行完成，结果：passed" in detail.text
    assert "学生自测" in detail.text
    assert "student_self_test" not in detail.text
    assert "是否有效" in detail.text
    assert "有效" in detail.text
    assert "+0800" in detail.text
    assert 'aria-valuenow="3"' in detail.text
    assert "题目已满足当前 Stage 提交要求" in detail.text
    assert "快照 Hash" not in detail.text
    assert "保存打包选择" not in detail.text
    assert "saveRunPackageSelection" in detail.text
    assert 'id="run-package-selection-form"' in detail.text
    assert "new FormData(selectionForm)" in detail.text
    assert 'class="link-button run-detail-trigger" type="button"' in detail.text
    run_table_start = detail.text.find("<h3>模型运行记录</h3>")
    run_table_end = detail.text.find("<h3>选中模型运行详情</h3>", run_table_start)
    assert "<th>温度</th>" not in detail.text[run_table_start:run_table_end]
    assert "#model-run-panel" not in response.headers["location"]
    assert "本次运行提示词" in detail.text
    assert "返回代码" in detail.text
    assert detail.text.find("<h3>返回代码</h3>") < detail.text.find("<h3>模型运行测试结果</h3>")
    assert "提取代码" not in detail.text
    assert "API 原始记录" not in detail.text
    assert "本次模型请求和返回内容已随运行记录保存" not in detail.text
    assert "<th>请求内容</th>" not in detail.text
    assert "<th>返回内容</th>" not in detail.text
    assert "API_KEY</th>" not in detail.text
    assert "Authorization 仅保存脱敏标记" not in detail.text
    assert "mock 提取代码" not in detail.text
    assert "p-0" in detail.text
    assert "a-4" in detail.text
    state = load_student_state(student_root)
    run_record = state["problems"][0]["run_records"][0]
    assert run_record["verdict"] == "passed"
    assert len(run_record["test_results"]) == 7
    assert run_record["api_response_raw"]["provider_api"] == "test_real_openai_chat_completions"
    assert run_record["api_response_raw"]["provider_api"] != "local_mock_openai_chat_completions"
    assert run_record["prompt_template_id"] == PROMPT_TEMPLATE_ID == "official_func_zh_v6"
    assert run_record["temperature"] == 0.0
    assert run_record["top_p"] == 1.0
    assert run_record["content_hash"]
    prompt = run_record["prompt"]
    assert prompt.startswith(f"请根据题目实现下面的 Python {EXECUTION_PYTHON_VERSION} 函数。")
    assert "Return x." in prompt
    assert "函数签名：\ndef solve(x: int) -> int:" in prompt
    assert f"运行环境：\nPython {EXECUTION_PYTHON_VERSION}" in prompt
    assert EXECUTION_PYTHON_IMAGE in prompt
    assert "复杂度要求" not in prompt
    assert "超时阈值" not in prompt
    assert "超时不算 failure mode" not in prompt
    assert "输出要求：\n只输出完整函数定义，第一行必须是上述函数签名" in prompt
    assert "只输出完整函数定义" in prompt
    assert "从上述函数签名开始；不要输出 Markdown、解释、测试代码或其它文本" not in prompt
    assert "不要使用 Markdown、代码块围栏、解释文字、标题、测试样例" not in prompt
    assert "示例 p-0" not in prompt
    assert '输入：{"x":1}；输出：1。' in prompt
    assert "kwargs=" not in prompt
    assert '"x":1' in prompt
    assert '"x":6' not in prompt
    assert run_record["prompt_parts"][1]["kind"] == "problem"
    assert run_record["prompt_parts"][1]["text"] == "Return x."
    assert run_record["api_request_raw"]["method"] == "POST"
    assert run_record["api_request_raw"]["url"] == "https://api.deepseek.com/chat/completions"
    assert run_record["api_request_raw"]["headers"]["Authorization"] == "Bearer [REDACTED]"
    assert run_record["api_request_raw"]["body"]["messages"][0]["content"] == prompt
    assert run_record["api_request_raw"]["body"]["temperature"] == 0.0
    assert run_record["api_request_raw"]["body"]["top_p"] == 1.0
    assert run_record["api_response_raw"]["choices"][0]["message"]["content"].startswith("def solve")
    assert "sk-student-secret" not in json.dumps(run_record, ensure_ascii=False)
    assert "sk-student-env-secret" not in json.dumps(run_record, ensure_ascii=False)
    assert run_record["package_selected"] is True

    run_id = run_record["run_id"]
    old_run = {**run_record, "run_id": "run_without_raw", "package_selected": False}
    old_run.pop("api_request_raw")
    old_run.pop("api_response_raw")
    state["problems"][0]["run_records"].append(old_run)
    save_student_state(student_root, state)
    response = client.post(
        f"{detail_path}/runs/package-selection",
        data={"package_run_ids": "run_without_raw"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    detail = client.get(response.headers["location"])
    assert "只能选择当前有效且记录完整的模型运行记录" in detail.text
    assert "记录不完整" in detail.text

    response = client.post(
        f"{detail_path}/runs/package-selection",
        data={"package_run_ids": run_id},
        follow_redirects=False,
    )
    assert response.status_code == 303
    detail = client.get(response.headers["location"])
    assert "已选择 1 条模型运行记录用于打包" in detail.text
    assert "已选打包" in detail.text
    state = load_student_state(student_root)
    run_record = state["problems"][0]["run_records"][0]
    assert run_record["package_selected"] is True

    response = client.post(
        f"{detail_path}/runs/package-selection",
        data={},
        headers={"X-Requested-With": "fetch"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["selected"] == 0
    assert payload["runs"][0]["run_id"] == run_id
    assert payload["runs"][0]["selected_for_package"] is False
    assert payload["runs"][0]["selectable_for_package"] is True
    assert payload["runs"][0]["package_status"] == "可选"
    state = load_student_state(student_root)
    assert state["problems"][0]["run_records"][0]["package_selected"] is False

    response = client.post(
        f"{detail_path}/runs/package-selection",
        data={"package_run_ids": run_id},
        headers={"X-Requested-With": "fetch"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["selected"] == 1
    assert payload["runs"][0]["selected_for_package"] is True
    assert payload["runs"][0]["package_status"] == "已选打包"

    response = client.post(
        f"{detail_path}/runs/package-selection",
        data={"_response_format": "json"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["selected"] == 0
    assert payload["runs"][0]["selected_for_package"] is False
    assert payload["runs"][0]["package_status"] == "可选"
    state = load_student_state(student_root)
    assert state["problems"][0]["run_records"][0]["package_selected"] is False

    response = client.post(
        f"{detail_path}/runs/package-selection",
        data={"package_run_ids": run_id, "_response_format": "json"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["selected"] == 1
    assert payload["runs"][0]["selected_for_package"] is True

    home = client.get("/stage1")
    assert "可选" in home.text

    for _ in range(4):
        _create_valid_selected_problem(client, student_root)
    _select_stage1_problem_package(client, student_root)
    response = client.post("/stage1/package", follow_redirects=False)
    assert response.status_code == 303
    package_name = response.headers["location"].split("download=", 1)[1]
    _, payload = read_package(student_root / "stage1-original/exports" / package_name)
    packaged_record = payload["problems"][0]["run_records"][0]
    assert packaged_record["api_request_raw"] == run_record["api_request_raw"]
    assert packaged_record["api_response_raw"] == run_record["api_response_raw"]
    assert len(payload["problems"][0]["run_records"]) == 1
    payload_json = json.dumps(payload, ensure_ascii=False)
    assert "sk-student-secret" not in payload_json
    assert "sk-student-env-secret" not in payload_json
    assert "API_KEY" not in payload_json
    assert packaged_record["api_request_raw"]["headers"]["Authorization"] == "Bearer [REDACTED]"

    changed_problem_data = {**valid_problem_data, "statement": "Return x unchanged."}
    response = client.post(
        f"{detail_path}/validate",
        data=changed_problem_data,
        follow_redirects=False,
    )
    assert response.status_code == 303
    state = load_student_state(student_root)
    changed_problem = state["problems"][0]
    assert changed_problem["run_records"][0]["package_selected"] is False
    response = client.post(
        f"{detail_path}/runs/package-selection",
        data={"package_run_ids": run_id},
        follow_redirects=False,
    )
    assert response.status_code == 303
    detail = client.get(response.headers["location"])
    assert "只能选择当前有效且记录完整的模型运行记录" in detail.text

    response = client.post(f"{detail_path}/runs/{run_id}/delete", follow_redirects=False)
    assert response.status_code == 303
    assert [run["run_id"] for run in load_student_state(student_root)["problems"][0]["run_records"]] == [
        "run_without_raw"
    ]

    invalid_problem_data = {
        **valid_problem_data,
        "public_expected_0": '{"any_of":[1,2]}',
    }
    response = client.post(
        f"{detail_path}/validate",
        data=invalid_problem_data,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "#validation-panel" in response.headers["location"]
    state = load_student_state(student_root)
    assert len(state["problems"][0]["run_records"]) == 1
    validation = state["problems"][0]["validation"]
    assert validation["status"] == "failed"
    assert validation["test_results"][0]["verdict"] == "error"
    assert "any_of" in validation["test_results"][0]["error"]
    detail = client.get(response.headers["location"])
    assert "用例格式有误" in detail.text
    assert '<span class="status-pill warn">未通过</span>' in detail.text
    assert 'id="model-run-status" data-valid="false"' in detail.text
    assert '<span class="status-pill warn">不可运行</span>' in detail.text
    assert "参考答案执行结果未通过" in detail.text
    assert "校验通过" not in detail.text
    assert '<span class="status-pill ok">可运行</span>' not in detail.text


def test_student_stage1_run_package_selection_draft_persists_across_page_reads(tmp_path):
    student_root = tmp_path / "student"
    client = TestClient(create_student_app(student_root))
    detail_path = _create_valid_selected_problem(client, student_root)
    data = _valid_problem_data()
    response = client.post(f"{detail_path}/run", data=data, follow_redirects=False)
    assert response.status_code == 303
    state = load_student_state(student_root)
    problem = state["problems"][0]
    run_ids = [run["run_id"] for run in problem["run_records"]]
    assert len(run_ids) == 2
    assert [run["package_selected"] for run in problem["run_records"]] == [True, True]
    assert "2 / 2" in client.get("/stage1").text

    response = client.post(
        f"{detail_path}/runs/package-selection",
        data={"package_run_ids": run_ids[1]},
        headers={"X-Requested-With": "fetch"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["selected"] == 1
    run_payload = {item["run_id"]: item for item in payload["runs"]}
    assert run_payload[run_ids[0]]["selected_for_package"] is False
    assert run_payload[run_ids[0]]["package_status"] == "可选"
    assert run_payload[run_ids[1]]["selected_for_package"] is True
    assert run_payload[run_ids[1]]["package_status"] == "已选打包"

    detail = client.get(detail_path)
    run_table = detail.text[
        detail.text.find("<h3>模型运行记录</h3>") : detail.text.find("<h3>选中模型运行详情</h3>")
    ]
    assert run_table.count("已选打包") == 1
    assert "1 / 2" in client.get("/stage1").text
    state = load_student_state(student_root)
    selected_after_read = [run["run_id"] for run in state["problems"][0]["run_records"] if run["package_selected"]]
    assert selected_after_read == [run_ids[1]]

    response = client.post(
        f"{detail_path}/runs/package-selection",
        data={},
        headers={"X-Requested-With": "fetch"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["selected"] == 0
    assert all(item["package_status"] == "可选" for item in payload["runs"])

    detail = client.get(detail_path)
    run_table = detail.text[
        detail.text.find("<h3>模型运行记录</h3>") : detail.text.find("<h3>选中模型运行详情</h3>")
    ]
    assert "已选打包" not in run_table
    assert run_table.count("可选") >= 2
    assert "0 / 2" in client.get("/stage1").text
    state = load_student_state(student_root)
    assert [run["package_selected"] for run in state["problems"][0]["run_records"]] == [False, False]


def test_student_stage1_real_api_error_creates_failed_unselectable_run(tmp_path, monkeypatch):
    def failing_completion(*, config, model, prompt, timeout=60.0):
        raise RuntimeError("真实模型请求失败：HTTP 400 model kfcvivo50 not found")

    monkeypatch.setattr("codesetarena.student_app.real_completion", failing_completion, raising=False)
    student_root = tmp_path / "student"
    client = TestClient(create_student_app(student_root))
    client.post(
        "/settings",
        data={
            "base_url": "https://api.example.test",
            "api_key": "sk-student-secret",
            "models": ["kfcvivo50"],
        },
    )
    response = client.post("/stage1/problems", follow_redirects=False)
    detail_path = response.headers["location"].split("?", 1)[0]
    data = {**_valid_problem_data(), "model": "kfcvivo50"}
    assert client.post(f"{detail_path}/validate", data=data, follow_redirects=False).status_code == 303

    response = client.post(f"{detail_path}/run", data=data, follow_redirects=False)

    assert response.status_code == 303
    run_records = load_student_state(student_root)["problems"][0]["run_records"]
    assert len(run_records) == 1
    run = run_records[0]
    assert run["verdict"] == "api_error"
    assert run["api_status"] == "failed"
    assert run["package_selected"] is False
    assert "真实模型请求失败：HTTP 400 model kfcvivo50 not found" in run["api_error"]
    page = client.get(response.headers["location"])
    assert "真实模型请求失败：HTTP 400 model kfcvivo50 not found" in page.text
    assert "API 请求状态" in page.text
    assert "<span" in page.text and "无效" in page.text


def test_student_run_record_content_hash_mismatch_invalidates_selection(tmp_path):
    student_root = tmp_path / "student"
    client = TestClient(create_student_app(student_root))
    client.post(
        "/settings",
        data={
            "base_url": "https://api.example.test",
            "api_key": "sk-student-secret",
            "models": ["deepseek-v4-flash"],
        },
    )
    detail_path = _create_valid_selected_problem(client, student_root)
    state = load_student_state(student_root)
    problem = state["problems"][0]
    assert problem["run_records"][0]["package_selected"] is True

    data = {**_valid_problem_data(), "author_expected_0": json.dumps(999)}
    response = client.post(f"{detail_path}/save", data=data, follow_redirects=False)

    assert response.status_code == 303
    changed = load_student_state(student_root)["problems"][0]
    assert changed["validation"]["status"] == "stale"
    assert changed["run_records"][0]["package_selected"] is False
    page = client.get(response.headers["location"])
    assert "已失效" in page.text


def test_settings_save_api_key_without_echoing_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-env-secret")
    monkeypatch.setenv("BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("MODELS", "deepseek-v4-flash|deepseek-v4-pro")
    student_root = tmp_path / "student"
    student = TestClient(create_student_app(student_root))
    response = student.get("/settings")
    assert "https://env.example/v1" not in response.text
    assert 'value="deepseek-v4-flash"' not in response.text
    assert 'value="deepseek-v4-pro"' not in response.text
    assert "data-add-model" in response.text
    assert "第一行是默认模型" not in response.text
    assert "API Key (API_KEY)" not in response.text
    assert "清空本端" not in response.text
    assert 'name="student_number"' not in response.text
    assert 'name="class_id"' not in response.text
    assert 'name="api_key" value=""' in response.text
    assert "sk-env-secret" not in response.text

    response = student.post(
        "/settings",
        data={
            "student_number": "2026000001",
            "name": "Alice",
            "class_id": "A",
            "base_url": "https://example.test/v1",
            "api_key": "sk-student-secret",
            "models": ["model-a", "model-b"],
        },
    )
    assert response.status_code == 200
    state = load_student_state(student_root)
    assert state["settings"]["api_key_set"] is True
    assert state["settings"]["api_key_source"] == str(student_root / ".env")
    assert "api_key" not in state["settings"]
    assert state["settings"]["models"] == ["model-a", "model-b"]
    assert "sk-student-secret" not in response.text
    assert "sk-env-secret" not in response.text

    student.post(
        "/settings",
        data={
            "student_number": "2026000001",
            "name": "Alice",
            "class_id": "A",
            "base_url": "https://example.test/v1",
            "models": "model-a",
        },
    )
    assert "api_key" not in load_student_state(student_root)["settings"]

    student.post(
        "/settings",
        data={
            "student_number": "2026000001",
            "name": "Alice",
            "class_id": "A",
            "base_url": "https://example.test/v1",
            "models": "model-a",
        },
    )
    assert load_student_state(student_root)["settings"]["api_key_set"] is True

    teacher_root = tmp_path / "teacher"
    teacher = TestClient(create_teacher_app(teacher_root))
    response = teacher.get("/settings")
    assert "https://env.example/v1" not in response.text
    assert 'value="deepseek-v4-flash"' not in response.text
    assert 'value="deepseek-v4-pro"' not in response.text
    assert "第一行是默认模型" not in response.text
    assert "API Key (API_KEY)" not in response.text
    assert 'name="api_key" value=""' in response.text
    assert "sk-env-secret" not in response.text

    response = teacher.post(
        "/settings",
        data={
            "course_name": "Course",
            "base_url": "https://example.test/v1",
            "api_key": "sk-teacher-secret",
            "models": ["judge-a"],
        },
    )
    assert response.status_code == 200
    state = load_teacher_state(teacher_root)
    assert state["settings"]["api_key_set"] is True
    assert state["settings"]["api_key_source"] == str(teacher_root / ".env")
    assert "api_key" not in state["settings"]
    assert "sk-teacher-secret" not in response.text
    assert "sk-env-secret" not in response.text


def test_student_info_global_panel_save_and_import_syncs(tmp_path):
    student_root = tmp_path / "student"
    student = TestClient(create_student_app(student_root))

    settings_html = student.get("/settings").text
    assert 'name="student_number"' not in settings_html
    assert "学号、姓名和班级请在 Stage 页面顶部" in settings_html

    for path in ["/stage1", "/stage2", "/stage3"]:
        html = student.get(path).text
        assert 'action="/student-info"' in html
        assert "<h2>学生信息</h2>" in html
        assert "student-info-fields" in html
        assert "保存学生信息" not in html
        assert "data-student-info-save" not in html
        assert "data-student-info-form" in html
        assert "已自动保存" not in html
        fields_match = re.search(r'<div class="student-info-fields">(?P<body>.*?)</div>', html, re.S)
        assert fields_match
        fields_html = fields_match.group("body")
        inline_pattern = (
            r'class="student-info-field-label"[^>]*>\s*学号\s*<span class="help-icon"'
            r'.*?</span>\s*</label>\s*<input[^>]+name="student_number"'
            r'.*?class="student-info-field-label"[^>]*>\s*姓名\s*<span class="help-icon"'
            r'.*?</span>\s*</label>\s*<input[^>]+name="name"'
            r'.*?class="student-info-field-label"[^>]*>\s*班级\s*<span class="help-icon"'
            r'.*?</span>\s*</label>\s*<input[^>]+name="class_id"'
        )
        assert re.search(inline_pattern, fields_html, re.S)

    for path, title in [
        ("/stage2", "Stage 2 匿名审稿"),
        ("/stage3", "Stage 3 修订与提交"),
    ]:
        html = student.get(path).text
        title_index = html.find(f"<h1>{title}</h1>")
        actions_index = html.find("<h2>清空当前 Stage 与导入包</h2>")
        student_info_index = html.find("<h2>学生信息</h2>")
        assert -1 not in {title_index, actions_index, student_info_index}
        assert title_index < actions_index < student_info_index
        assert html.find('action="/stage2/reset"' if path == "/stage2" else 'action="/stage3/reset"') > actions_index
        assert html.find('action="/stage2/import"' if path == "/stage2" else 'action="/stage3/import"') > actions_index

    response = student.post(
        "/student-info",
        data={"student_number": "2026000098", "name": "Dina", "class_id": "B0"},
        headers={"X-Requested-With": "fetch"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert load_student_state(student_root)["student"] == {
        "student_number": "2026000098",
        "name": "Dina",
        "class_id": "B0",
    }

    response = student.post(
        "/student-info",
        data={"student_number": "2026000099", "name": "Dana", "class_id": "B1", "next": "/stage2"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/stage2")
    state = load_student_state(student_root)
    assert state["student"] == {"student_number": "2026000099", "name": "Dana", "class_id": "B1"}
    assert "2026000099" in student.get("/stage1").text

    stage1_archive = _make_stage1_package(tmp_path, "2026000100", "Eve")
    _upload(student, "/stage1/import", stage1_archive)
    state = load_student_state(student_root)
    assert state["student"] == {"student_number": "2026000100", "name": "Eve", "class_id": "A"}
    assert len(state["problems"]) == PROBLEMS_PER_STUDENT

    stage2_root = tmp_path / "stage2-blank-student"
    stage2_student = TestClient(create_student_app(stage2_root))
    assignment = _make_review_assignment_package(tmp_path, "2026000101")
    _upload(stage2_student, "/stage2/import", assignment)
    assert load_student_state(stage2_root)["student"]["student_number"] == "2026000101"

    stage3_root = tmp_path / "stage3-blank-student"
    stage3_student = TestClient(create_student_app(stage3_root))
    feedback = _make_review_feedback_package(tmp_path, "2026000102")
    _upload(stage3_student, "/stage3/import", feedback)
    assert load_student_state(stage3_root)["student"]["student_number"] == "2026000102"


def test_student_stage1_package_selection_autosaves_partial_valid_set(tmp_path):
    student_root = tmp_path / "student"
    client = TestClient(create_student_app(student_root))
    client.post("/student-info", data={"student_number": "2026000001", "name": "Alice", "class_id": "A"})
    detail_path = _create_valid_selected_problem(client, student_root)
    problem_id = detail_path.rsplit("/", 1)[1]

    response = client.post(
        "/stage1/problems/package-selection",
        data={"package_problem_ids": problem_id},
        headers={"X-Requested-With": "fetch"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "selected": 1}
    state = load_student_state(student_root)
    assert state["problems"][0]["stage1_package_selected"] is True

    response = client.post(
        "/stage1/problems/package-selection",
        data={},
        headers={"X-Requested-With": "fetch"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "selected": 0}
    assert load_student_state(student_root)["problems"][0]["stage1_package_selected"] is False

    response = client.post(
        "/stage1/problems/package-selection",
        data={"package_problem_ids": problem_id, "_response_format": "json"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "selected": 1}

    response = client.post(
        "/stage1/problems/package-selection",
        data={"_response_format": "json"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "selected": 0}
    assert load_student_state(student_root)["problems"][0]["stage1_package_selected"] is False


def test_settings_api_key_save_keep_clear_and_invalid(tmp_path, monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.delenv("MODELS", raising=False)

    student_root = tmp_path / "student"
    student = TestClient(create_student_app(student_root))
    response = student.post(
        "/settings",
        data={
            "student_number": "2026000001",
            "name": "Alice",
            "class_id": "A",
            "api_key": "bad-key",
            "base_url": "https://example.test/v1",
            "models": ["model-a"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    assert not (student_root / ".env").exists()

    response = student.post(
        "/settings",
        data={
            "student_number": "2026000001",
            "name": "Alice",
            "class_id": "A",
            "api_key": "sk-local-student-key",
            "base_url": "https://example.test/v1",
            "models": ["model-a"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    state = load_student_state(student_root)
    assert state["settings"]["api_key_set"] is True
    assert "api_key" not in state["settings"]
    assert "sk-local-student-key" not in (student_root / "student-state.json").read_text(encoding="utf-8")
    page = student.get("/settings")
    assert "sk-local-student-key" not in page.text
    assert 'name="api_key" value="******"' in page.text

    response = student.post(
        "/settings",
        data={
            "student_number": "2026000001",
            "name": "Alice",
            "class_id": "A",
            "api_key": "******",
            "base_url": "https://example.test/v1",
            "models": ["model-a"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert load_student_state(student_root)["settings"]["api_key_set"] is True

    response = student.post(
        "/settings",
        data={
            "student_number": "2026000001",
            "name": "Alice",
            "class_id": "A",
            "api_key": "",
            "base_url": "https://example.test/v1",
            "models": ["model-a"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    assert load_student_state(student_root)["settings"]["api_key_set"] is True
    assert "sk-local-student-key" in (student_root / ".env").read_text(encoding="utf-8")

    teacher_root = tmp_path / "teacher"
    teacher = TestClient(create_teacher_app(teacher_root))
    response = teacher.post(
        "/settings",
        data={"course_name": "Course", "api_key": "bad-key", "base_url": "https://example.test/v1", "models": ["judge-a"]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    assert not (teacher_root / ".env").exists()

    response = teacher.post(
        "/settings",
        data={"course_name": "Course", "api_key": "sk-local-teacher-key", "base_url": "https://example.test/v1", "models": ["judge-a"]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert load_teacher_state(teacher_root)["settings"]["api_key_set"] is True
    assert "sk-local-teacher-key" not in (teacher_root / "teacher-state.json").read_text(encoding="utf-8")

    response = teacher.post(
        "/settings",
        data={"course_name": "Course", "api_key": "", "base_url": "https://example.test/v1", "models": ["judge-a"]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    assert load_teacher_state(teacher_root)["settings"]["api_key_set"] is True


def test_form_controls_have_length_limits_and_help_tooltips(tmp_path):
    student_root = tmp_path / "student"
    student = TestClient(create_student_app(student_root))
    student.post("/student-info", data={"student_number": "2026000001", "name": "Alice", "class_id": "A"})

    _assert_controls_are_guided(student.get("/settings").text)

    response = student.post("/stage1/problems", follow_redirects=False)
    detail_path = response.headers["location"].split("?", 1)[0]
    _assert_controls_are_guided(student.get(detail_path).text)

    teacher_root = tmp_path / "teacher"
    teacher = TestClient(create_teacher_app(teacher_root))
    _assert_controls_are_guided(teacher.get("/settings").text)
    _assert_controls_are_guided(teacher.get("/stage1").text)
    _assert_controls_are_guided(teacher.get("/stage2/assign").text)
    _assert_controls_are_guided(teacher.get("/stage2/reviews").text)
    _assert_controls_are_guided(teacher.get("/stage3/revisions").text)

    assignment = _make_review_assignment_package(tmp_path, "2026000001")
    _upload(student, "/stage2/import", assignment)
    _assert_controls_are_guided(student.get("/stage2").text)

    feedback = _make_review_feedback_package(tmp_path, "2026000001")
    _upload(student, "/stage3/import", feedback)
    _assert_controls_are_guided(student.get("/stage3").text)


def test_form_length_limits_are_enforced(tmp_path):
    student_root = tmp_path / "student"
    student = TestClient(create_student_app(student_root))

    response = student.post(
        "/student-info",
        data={
            "student_number": "2" * (FORM_LIMITS["student_number"] + 1),
            "name": "Alice",
            "class_id": "A",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]

    _configure_student_model_settings(student)
    student.post("/student-info", data={"student_number": "2026000001", "name": "Alice", "class_id": "A"})
    response = student.post("/stage1/problems", follow_redirects=False)
    detail_path = response.headers["location"].split("?", 1)[0]
    too_long_problem = {**_valid_problem_data(), "statement": "x" * (FORM_LIMITS["problem_statement"] + 1)}
    response = student.post(f"{detail_path}/validate", data=too_long_problem, follow_redirects=False)
    assert response.status_code == 303
    assert "error=" in response.headers["location"]

    assignment = _make_review_assignment_package(tmp_path, "2026000001")
    _upload(student, "/stage2/import", assignment)
    assignment_state = load_student_state(student_root)["assignment"]
    anon_id = assignment_state["assigned_problems"][0]["anonymous_id"]
    response = student.post(
        "/stage2/package",
        data={
            f"conclusion_{anon_id}": "major",
            f"explanation_{anon_id}": "s" * (FORM_LIMITS["review_explanation"] + 1),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]

    stage3_root = tmp_path / "student-stage3"
    stage3_student = TestClient(create_student_app(stage3_root))
    _prepare_student_with_five_problems(stage3_student, stage3_root, "2026000001", "Alice")
    feedback = _make_review_feedback_package(tmp_path, "2026000001")
    _upload(stage3_student, "/stage3/import", feedback)
    feedback_state = load_student_state(stage3_root)["feedback"]
    review_id = feedback_state["reviews_for_author"][0]["review_id"]
    response = stage3_student.post(
        "/stage3/package",
        data={
            f"rating_{review_id}": "5",
            f"response_{review_id}": "r" * (FORM_LIMITS["author_response"] + 1),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]

    teacher_root = tmp_path / "teacher"
    teacher = TestClient(create_teacher_app(teacher_root))
    response = teacher.post(
        "/settings",
        data={"course_name": "c" * (FORM_LIMITS["course_name"] + 1)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]

    response = teacher.post(
        "/stage2/assign",
        data={"reviews_per_problem": "100"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]

    response = teacher.post(
        "/settings",
        data={"course_name": "CodeSetArena v7", "random_seed": "not-a-number"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]


def test_teacher_settings_random_seed_default_and_save(tmp_path):
    teacher_root = tmp_path / "teacher"
    teacher = TestClient(create_teacher_app(teacher_root))

    settings = teacher.get("/settings")
    assert "随机种子" in settings.text
    assert 'name="random_seed" value="42"' in settings.text

    response = teacher.post(
        "/settings",
        data={
            "course_name": "CodeSetArena v7",
            "random_seed": "123",
            "base_url": "https://api.example.test",
            "api_key": "sk-teacher-secret",
            "models": ["model-a"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    state = load_teacher_state(teacher_root)
    assert state["settings"]["random_seed"] == 123


def test_teacher_stage2_assign_page_handles_legacy_state_without_manifest(tmp_path):
    teacher_root = tmp_path / "teacher"
    teacher_root.mkdir()
    (teacher_root / "teacher-state.json").write_text(
        json.dumps(
            {
                "settings": {
                    "course_name": "CodeSetArena v7",
                    "models": ["deepseek-v4-flash"],
                },
                "submissions": {},
                "assignments": {},
                "reviews": {},
                "feedback": {},
                "revisions": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    teacher = TestClient(create_teacher_app(teacher_root), raise_server_exceptions=False)

    page = teacher.get("/stage2/assign")

    assert page.status_code == 200
    assert "暂无匿名用户映射" in page.text
    assert "暂无匿名题目映射" in page.text


def test_teacher_stage2_assignment_is_seeded_and_repeatable(tmp_path):
    teacher_root = tmp_path / "teacher"
    teacher = TestClient(create_teacher_app(teacher_root))
    for student_number, name in [
        ("2026000001", "Alice"),
        ("2026000002", "Bob"),
        ("2026000003", "Carol"),
    ]:
        _upload(teacher, "/stage1/upload", _make_stage1_package(tmp_path, student_number, name))

    teacher.post(
        "/settings",
        data={
            "course_name": "CodeSetArena v7",
            "random_seed": "7",
            "base_url": "https://api.example.test",
            "api_key": "sk-teacher-secret",
            "models": ["deepseek-v4-flash"],
        },
    )
    first = teacher.post("/stage2/assign", data={"reviews_per_problem": "3"}, follow_redirects=False)
    assert first.status_code == 303
    first_state = load_teacher_state(teacher_root)
    first_assignments = json.loads(json.dumps(first_state["assignments"], sort_keys=True))
    first_manifest = json.loads(json.dumps(first_state["stage2_assignment_manifest"], sort_keys=True))

    second = teacher.post("/stage2/assign", data={"reviews_per_problem": "3"}, follow_redirects=False)
    assert second.status_code == 303
    second_state = load_teacher_state(teacher_root)
    assert second_state["assignments"] == first_assignments
    assert second_state["stage2_assignment_manifest"] == first_manifest

    teacher.post(
        "/settings",
        data={
            "course_name": "CodeSetArena v7",
            "random_seed": "8",
            "base_url": "https://api.example.test",
            "api_key": "sk-teacher-secret",
            "models": ["deepseek-v4-flash"],
        },
    )
    third = teacher.post("/stage2/assign", data={"reviews_per_problem": "3"}, follow_redirects=False)
    assert third.status_code == 303
    third_state = load_teacher_state(teacher_root)
    assert third_state["stage2_assignment_manifest"] != first_manifest


def test_teacher_stage2_assignment_balances_human_reviewer_load(tmp_path):
    teacher_root = tmp_path / "teacher"
    teacher = TestClient(create_teacher_app(teacher_root))
    student_numbers = [str(number) for number in range(1001, 1011)]
    for student_number in student_numbers:
        _upload(teacher, "/stage1/upload", _make_stage1_package(tmp_path, student_number, f"学生{student_number}"))

    teacher.post(
        "/settings",
        data={
            "course_name": "CodeSetArena v7",
            "random_seed": "42",
            "base_url": "https://api.example.test",
            "api_key": "sk-teacher-secret",
            "models": ["deepseek-v4-flash"],
        },
    )
    response = teacher.post("/stage2/assign", data={"reviews_per_problem": "4"}, follow_redirects=False)

    assert response.status_code == 303
    state = load_teacher_state(teacher_root)
    assignments = state["stage2_assignment_manifest"]["assignments"]
    by_problem = defaultdict(list)
    human_loads = Counter({student_number: 0 for student_number in student_numbers})
    ai_count = 0
    for item in assignments:
        key = (item["author_student_number"], item["problem_id"], item["problem_index"])
        by_problem[key].append(item)
        if item["review_origin"] == "human":
            assert item["reviewer_student_number"] != item["author_student_number"]
            human_loads[item["reviewer_student_number"]] += 1
        else:
            assert item["reviewer_student_number"] == AI_REVIEWER_STUDENT_NUMBER
            ai_count += 1

    assert len(by_problem) == len(student_numbers) * PROBLEMS_PER_STUDENT
    assert ai_count == len(by_problem)
    assert all(len(items) == 4 for items in by_problem.values())
    assert all(sum(1 for item in items if item["review_origin"] == "ai") == 1 for items in by_problem.values())
    assert all(sum(1 for item in items if item["review_origin"] == "human") == 3 for items in by_problem.values())
    assert set(human_loads.values()) == {15}


def test_student_validation_reports_python_environment_error(tmp_path):
    student_root = tmp_path / "student"
    student = TestClient(create_student_app(student_root))
    _configure_student_model_settings(student)
    student.post("/student-info", data={"student_number": "2026000001", "name": "Alice", "class_id": "A"})
    response = student.post("/stage1/problems", follow_redirects=False)
    detail_path = response.headers["location"].split("?", 1)[0]

    data = {
        **_valid_problem_data(),
        "reference_solution": "def solve(x: int) -> int:\n    return x +\n",
    }
    response = student.post(f"{detail_path}/validate", data=data, follow_redirects=False)
    assert response.status_code == 303
    detail = student.get(response.headers["location"])
    assert "Python 版本" in detail.text
    assert "语法" in detail.text
    assert "python_version_error" in detail.text


def test_teacher_student_course_roundtrip(tmp_path):
    teacher_root = tmp_path / "teacher"
    teacher = TestClient(create_teacher_app(teacher_root))
    stage1_a = _make_stage1_package(tmp_path, "2026000001", "Alice")
    stage1_b = _make_stage1_package(tmp_path, "2026000002", "Bob")

    _upload(teacher, "/stage1/upload", stage1_a)
    _upload(teacher, "/stage1/upload", stage1_b)

    response = teacher.post(
        "/stage2/assign",
        data={"reviews_per_problem": "2"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "teacher-stage2-review-assignments.tar.gz" in response.headers["location"]

    assignment_a = (
        teacher_root
        / "stage2-review-assignment/review-packages"
        / teacher_package_name("2026000001", STAGE2, "review-assignment")
    )
    assert assignment_a.exists()
    bundle = (
        teacher_root
        / "stage2-review-assignment/review-packages/teacher-stage2-review-assignments.tar.gz"
    )
    stage2_bundle_manifest = _read_bundle_manifest(bundle)
    assert stage2_bundle_manifest["schema_version"] == "codesetarena.teacher-bundle.v1"
    assert stage2_bundle_manifest["stage"] == STAGE2
    assert stage2_bundle_manifest["kind"] == "review-assignments"
    assert stage2_bundle_manifest["random_seed"] == 42
    assert "bundle-manifest.json" in _tar_names(bundle)
    assert len(stage2_bundle_manifest["anonymous_user_map"]) == 3
    assert len(stage2_bundle_manifest["anonymous_problem_map"]) == 2 * PROBLEMS_PER_STUDENT
    assert all(
        item["reviewer_student_number"] != item["author_student_number"]
        for item in stage2_bundle_manifest["assignments"]
        if item["review_origin"] == "human"
    )
    assign_page = teacher.get("/stage2/assign").text
    assert "匿名用户 ID" in assign_page
    assert "真实用户 ID" in assign_page
    assert "匿名题目 ID" in assign_page
    assert "真实题目 ID" in assign_page
    _, assignment_payload = read_package(assignment_a)
    assert assignment_payload["reviews_per_problem"] == 2
    assert assignment_payload["human_reviews_per_problem"] == 1
    assert assignment_payload["ai_reviews_per_problem"] == 1
    assert assignment_payload["review_origin"] == "human"
    assert len(assignment_payload["assigned_problems"]) == PROBLEMS_PER_STUDENT
    assigned_problem = assignment_payload["assigned_problems"][0]
    assert assigned_problem["review_origin"] == "human"
    assert assigned_problem["anonymous_id"].startswith("anon_problem_")
    assert assigned_problem["anonymous_problem_id"] == assigned_problem["anonymous_id"]
    assert assigned_problem["anonymous_author_id"].startswith("anon_user_")
    assert "author_student_number" not in assigned_problem
    assert assigned_problem["statement"] == "Return x."
    assert assigned_problem["signature"] == "def solve(x: int) -> int:"
    assert assigned_problem["reference_solution"] == "def solve(x: int) -> int:\n    return x\n"
    assert len(assigned_problem["public_tests"]) == PUBLIC_TESTS_PER_PROBLEM
    assert len(assigned_problem["author_tests"]) == AUTHOR_TESTS_PER_PROBLEM
    assert assigned_problem["run_records"][0]["run_id"].startswith("run_")
    assert assigned_problem["run_records"][0]["verdict"] == "passed"
    assert assigned_problem["run_records"][0]["extracted_code"] == "def solve(x: int) -> int:\n    return x\n"

    ai_assignment = (
        teacher_root
        / "stage2-review-assignment/review-packages"
        / teacher_package_name(AI_REVIEWER_STUDENT_NUMBER, STAGE2, "review-assignment")
    )
    assert ai_assignment.exists()
    _, ai_payload = read_package(ai_assignment)
    assert ai_payload["student"] == {
        "student_number": "AI",
        "name": "AI",
        "class_id": "AI",
    }
    assert ai_payload["reviews_per_problem"] == 2
    assert ai_payload["human_reviews_per_problem"] == 1
    assert ai_payload["ai_reviews_per_problem"] == 1
    assert ai_payload["review_origin"] == "ai"
    assert len(ai_payload["assigned_problems"]) == 2 * PROBLEMS_PER_STUDENT
    assert all(item["review_origin"] == "ai" for item in ai_payload["assigned_problems"])
    assert all("author_student_number" not in item for item in ai_payload["assigned_problems"])
    teacher_state = load_teacher_state(teacher_root)
    assert AI_REVIEWER_STUDENT_NUMBER in teacher_state["assignments"]
    assert len(teacher_state["assignments"][AI_REVIEWER_STUDENT_NUMBER]) == 2 * PROBLEMS_PER_STUDENT

    student_a_root = tmp_path / "student-a"
    student_a = TestClient(create_student_app(student_a_root))
    _prepare_student_with_five_problems(student_a, student_a_root, "2026000001", "Alice")
    _upload(student_a, "/stage2/import", assignment_a)
    stage2_html = student_a.get("/stage2").text
    assert "题目完整详情" in stage2_html
    assert "参考答案" in stage2_html
    assert "样例数据" in stage2_html
    assert "测试数据" in stage2_html
    assert "提交的自测运行结果" in stage2_html
    assert "返回代码" in stage2_html
    assert "run_0" in stage2_html
    assert "运行结果 1" in stage2_html
    assert "review-run-card" in stage2_html
    assert "输入" in stage2_html
    assert "输出" in stage2_html
    assert "结论" in stage2_html
    assert "accept" in stage2_html
    assert "minor" in stage2_html
    assert "major" in stage2_html
    assert "reject" in stage2_html
    assert '<option value="" selected>未选择</option>' in stage2_html
    assert "严重程度" not in stage2_html
    assert "可选 regression test" not in stage2_html
    assert "data-stage2-review-autosave" in stage2_html
    assert "/stage2/reviews/draft" in stage2_html
    assignment_state = load_student_state(student_a_root)["assignment"]
    first_anon_id = assignment_state["assigned_problems"][0]["anonymous_id"]

    response = student_a.post(
        "/stage2/reviews/draft",
        data={
            "anonymous_id": first_anon_id,
            f"conclusion_{first_anon_id}": "minor",
            f"explanation_{first_anon_id}": "建议补充边界样例",
            f"quality_score_{first_anon_id}": "4",
        },
        headers={"X-Requested-With": "fetch"},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "anonymous_id": first_anon_id}
    state = load_student_state(student_a_root)
    assert state["reviews"][first_anon_id] == {
        "anonymous_id": first_anon_id,
        "conclusion": "minor",
        "explanation": "建议补充边界样例",
        "quality_score": "4",
    }
    stage2_html = student_a.get("/stage2").text
    assert '<option value="minor" selected>minor</option>' in stage2_html
    assert "建议补充边界样例</textarea>" in stage2_html

    missing_conclusion_form = _review_form_for_assignment(assignment_state)
    missing_conclusion_form[f"conclusion_{first_anon_id}"] = ""
    response = student_a.post(
        "/stage2/package",
        data=missing_conclusion_form,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "package_error=" in response.headers["location"]
    assert "?error=" not in response.headers["location"]
    assert "&error=" not in response.headers["location"]
    detail = student_a.get(response.headers["location"])
    assert 'id="notice-region"' in detail.text
    assert '<div class="notice error">导出审稿包失败' not in detail.text
    assert "请为每道题选择审稿结论" in detail.text
    assert "conclusion must be one of" not in detail.text

    missing_suggestion_form = _review_form_for_assignment(assignment_state)
    missing_suggestion_form[f"explanation_{first_anon_id}"] = ""
    response = student_a.post(
        "/stage2/package",
        data=missing_suggestion_form,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "package_error=" in response.headers["location"]
    detail = student_a.get(response.headers["location"])
    assert "请填写每道题的审稿建议" in detail.text
    assert "review suggestion is required" not in detail.text

    missing_quality_form = _review_form_for_assignment(assignment_state)
    missing_quality_form[f"quality_score_{first_anon_id}"] = ""
    response = student_a.post(
        "/stage2/package",
        data=missing_quality_form,
        follow_redirects=False,
    )
    assert response.status_code == 303
    detail = student_a.get(response.headers["location"])
    assert "请为每道题选择题目质量评分" in detail.text

    legacy_detail = student_a.get(
        "/stage2?error=导出审稿包失败：anon_legacy+review+suggestion+is+required"
    )
    assert '<div class="notice error">导出审稿包失败' not in legacy_detail.text
    assert "请填写每道题的审稿建议" in legacy_detail.text

    response = student_a.post(
        "/stage2/package",
        data=_review_form_for_assignment(assignment_state),
        follow_redirects=False,
    )
    assert response.status_code == 303
    review_name = student_package_name("2026000001", STAGE2, KIND_REVIEWS)
    review_archive = student_a_root / "stage2-review/exports" / review_name
    assert review_archive.exists()
    _, review_payload = read_package(review_archive)
    assert len(review_payload["reviews"]) == PROBLEMS_PER_STUDENT
    assert review_payload["reviews"][0]["conclusion"] == "major"
    assert review_payload["reviews"][0]["explanation"]
    assert review_payload["reviews"][0]["quality_score"] == "4"
    assert "severity" not in review_payload["reviews"][0]
    assert "regression_test" not in review_payload["reviews"][0]

    _upload(teacher, "/stage2/reviews/upload", review_archive)
    review_detail = teacher.get("/stage2/reviews/2026000001").text
    assert "审稿包详情" in review_detail
    assert "匿名题目" in review_detail
    assert "真实学号" in review_detail
    assert "原始 JSON" in review_detail
    response = teacher.post("/stage3/feedback", follow_redirects=False)
    assert response.status_code == 303
    assert "teacher-stage3-review-feedbacks.tar.gz" in response.headers["location"]
    feedback_bundle = teacher_root / "stage3-revisions/feedback-packages/teacher-stage3-review-feedbacks.tar.gz"
    stage3_bundle_manifest = _read_bundle_manifest(feedback_bundle)
    assert stage3_bundle_manifest["schema_version"] == "codesetarena.teacher-bundle.v1"
    assert stage3_bundle_manifest["stage"] == STAGE3
    assert stage3_bundle_manifest["kind"] == "review-feedbacks"
    assert stage3_bundle_manifest["random_seed"] == 42
    assert "bundle-manifest.json" in _tar_names(feedback_bundle)

    feedback_b = (
        teacher_root
        / "stage3-revisions/feedback-packages"
        / teacher_package_name("2026000002", STAGE3, "review-feedback")
    )
    assert feedback_b.exists()

    student_b_root = tmp_path / "student-b"
    student_b = TestClient(create_student_app(student_b_root))
    _prepare_student_with_five_problems(student_b, student_b_root, "2026000002", "Bob")
    _upload(student_b, "/stage3/import", feedback_b)
    feedback_state = load_student_state(student_b_root)["feedback"]
    response = student_b.post(
        "/stage3/package",
        data=_response_form_for_feedback(feedback_state),
        follow_redirects=False,
    )
    assert response.status_code == 303
    revision_name = student_package_name("2026000002", STAGE3, KIND_REVISION)
    revision_archive = student_b_root / "stage3-revision/exports" / revision_name
    assert revision_archive.exists()

    _upload(teacher, "/stage3/revisions/upload", revision_archive)
    revision_detail = teacher.get("/stage3/revisions/2026000002").text
    assert "修订包详情" in revision_detail
    assert "修订题目" in revision_detail
    assert "回应建议" in revision_detail
    assert "原始 JSON" in revision_detail
    teacher.post(
        "/settings",
        data={
            "course_name": "CodeSetArena v7",
            "random_seed": "42",
            "base_url": "https://api.example.test",
            "api_key": "sk-teacher-secret",
            "models": ["deepseek-v4-flash"],
        },
    )
    response = teacher.post("/eval/run", follow_redirects=False)
    assert response.status_code == 303
    eval_archive = teacher_root / "ta-eval/runs/teacher-stage4-official-eval.tar.gz"
    manifest, payload = read_package(eval_archive)
    assert manifest["package_role"] == ROLE_TEACHER
    assert payload["eval_runs"][0]["run_origin"] == "ta_official_eval"

    response = teacher.post("/stats/export", follow_redirects=False)
    assert response.status_code == 303
    assert (teacher_root / "stats/exports/teacher-stage4-course-stats.json").exists()


def test_student_stage3_groups_reviews_by_problem_and_requires_rating(tmp_path):
    student_root = tmp_path / "student"
    student = TestClient(create_student_app(student_root))
    _prepare_student_with_five_problems(student, student_root, "2026000001", "Alice")
    problem_id = load_student_state(student_root)["problems"][0]["problem_id"]
    feedback = _make_review_feedback_package(tmp_path, "2026000001", problem_id=problem_id, review_count=2)

    _upload(student, "/stage3/import", feedback)
    html = student.get("/stage3").text
    card_start = html.find(f'id="stage3-problem-{problem_id}"')
    card_end = html.find('<section class="panel package">', card_start)
    card_html = html[card_start:card_end]
    stage3_section_order = [
        "题目状态",
        "<h2>题目信息</h2>",
        "<h2>保存与校验</h2>",
        "参考答案执行结果",
        "<h2>模型执行运行</h2>",
        "<h3>模型提示词</h3>",
        "<h3>模型运行记录</h3>",
        "<h3>选中模型运行详情</h3>",
        "<h2>说明</h2>",
        "<h3>审稿意见评分与回应建议</h3>",
    ]
    indexes = [card_html.find(marker) for marker in stage3_section_order]
    assert -1 not in indexes
    assert indexes == sorted(indexes)
    assert "problem-progress-panel" in card_html
    assert 'aria-valuemax="4"' in card_html
    assert 'aria-valuenow="3"' in card_html
    assert "审稿回应完成" in card_html
    assert "请完成审稿意见评分和回应" in card_html
    assert "<span>运行记录</span>" not in card_html
    assert "<span>合法运行</span>" not in card_html
    assert "<span>不 pass</span>" not in card_html
    assert "<span>参考答案失败</span>" not in card_html
    assert "修订后的题目" not in card_html
    assert "校验与模型自测" not in card_html
    assert "保存并校验</button>" not in card_html
    assert "运行自测</button>" not in card_html
    assert "<h3>模型自测记录</h3>" not in card_html
    assert "data-stage3-ajax" in html
    assert "novalidate" in html
    assert "stage3-package-status" in html
    assert "validateStage3PackageForm" in html
    assert "updateStage3ReviewProgress" in html
    assert "handleStage3PackageJson" in html
    assert 'hasAttribute("formaction")' in html
    assert "window.scrollTo(savedScrollX, savedScrollY)" in html
    assert "审稿意见评分与回应建议" in html
    assert "AuthorReviewRating" not in html
    assert "审稿意见评分" in html
    assert "未评分" in html
    assert "5分：对本题改进非常关键" in html
    assert "4分：对本题改进很有帮助" in html
    assert "3分：对本题改进有一定帮助" in html
    assert "1分：基本无帮助" in html
    assert "5分：完全采纳" not in html
    assert "4分：部分采纳" not in html
    assert "处理状态" not in html
    assert "打开题目详情修改" not in html
    assert "样例数据" in html
    assert "测试数据" in html

    revised_data = {**_valid_problem_data(), "statement": "Return x after review."}
    response = student.post(
        f"/stage3/problems/{problem_id}/validate",
        data=revised_data,
        follow_redirects=False,
    )
    assert response.status_code == 303
    response = student.post(
        f"/stage3/problems/{problem_id}/run",
        data=revised_data,
        follow_redirects=False,
    )
    assert response.status_code == 303
    revised_problem = next(item for item in load_student_state(student_root)["problems"] if item["problem_id"] == problem_id)
    run_id = revised_problem["run_records"][0]["run_id"]
    html = student.get("/stage3").text
    card_start = html.find(f'id="stage3-problem-{problem_id}"')
    card_end = html.find('<section class="panel package">', card_start)
    card_html = html[card_start:card_end]
    run_table = card_html[
        card_html.find("<h3>模型运行记录</h3>") : card_html.find("<h3>选中模型运行详情</h3>")
    ]
    assert "<th>温度</th>" not in run_table

    response = student.post(
        f"/stage3/problems/{problem_id}/runs/package-selection",
        data={"package_run_ids": run_id},
        follow_redirects=False,
    )
    assert response.status_code == 303
    response = student.post(
        f"/stage3/problems/{problem_id}/runs/package-selection",
        data={},
        headers={"X-Requested-With": "fetch"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    html = student.get("/stage3").text
    card_start = html.find(f'id="stage3-problem-{problem_id}"')
    card_end = html.find('<section class="panel package">', card_start)
    card_html = html[card_start:card_end]
    run_table = card_html[
        card_html.find("<h3>模型运行记录</h3>") : card_html.find("<h3>选中模型运行详情</h3>")
    ]
    assert "已选打包" not in run_table
    assert "可选" in run_table
    revised_problem = next(item for item in load_student_state(student_root)["problems"] if item["problem_id"] == problem_id)
    assert revised_problem["run_records"][0]["package_selected"] is False

    response = student.post(
        f"/stage3/problems/{problem_id}/runs/package-selection",
        data={"package_run_ids": run_id},
        follow_redirects=False,
    )
    assert response.status_code == 303

    review_ids = [item["review_id"] for item in load_student_state(student_root)["feedback"]["reviews_for_author"]]
    response = student.post(
        "/stage3/package",
        data={
            f"rating_{review_ids[0]}": "5",
            f"response_{review_ids[0]}": "已采纳第一条意见",
            f"rating_{review_ids[1]}": "",
            f"response_{review_ids[1]}": "已阅读第二条意见",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]

    response = student.post(
        "/stage3/package",
        data={
            f"rating_{review_ids[0]}": "5",
            f"response_{review_ids[0]}": "已采纳第一条意见",
            f"rating_{review_ids[1]}": "",
            f"response_{review_ids[1]}": "已阅读第二条意见",
        },
        headers={"X-Requested-With": "fetch"},
    )
    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert "导出修订包失败" in response.json()["message"]

    response = student.post(
        "/stage3/package",
        data={
            f"rating_{review_ids[0]}": "5",
            f"response_{review_ids[0]}": "已采纳第一条意见",
            f"rating_{review_ids[1]}": "3",
            f"response_{review_ids[1]}": "第二条意见部分参考",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    revision_archive = (
        student_root
        / "stage3-revision/exports"
        / student_package_name("2026000001", STAGE3, KIND_REVISION)
    )
    _, payload = read_package(revision_archive)
    assert len(payload["responses"]) == 2
    assert all("status" not in item for item in payload["responses"])
    exported_problem = next(item for item in payload["problems"] if item["problem_id"] == problem_id)
    assert exported_problem["statement"] == "Return x after review."
    assert exported_problem["run_records"][0]["run_id"] == run_id

    response = student.post(
        "/stage3/package",
        data={
            "_response_format": "json",
            f"rating_{review_ids[0]}": "5",
            f"response_{review_ids[0]}": "已采纳第一条意见",
            f"rating_{review_ids[1]}": "3",
            f"response_{review_ids[1]}": "第二条意见部分参考",
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["download"] == student_package_name("2026000001", STAGE3, KIND_REVISION)


def test_teacher_student_joint_syncs_imported_student_info_and_rejects_wrong_role_package(tmp_path):
    teacher_root = tmp_path / "teacher"
    teacher = TestClient(create_teacher_app(teacher_root))
    stage1_a = _make_stage1_package(tmp_path, "2026000001", "Alice")
    stage1_b = _make_stage1_package(tmp_path, "2026000002", "Bob")

    _upload(teacher, "/stage1/upload", stage1_a)
    _upload(teacher, "/stage1/upload", stage1_b)
    response = teacher.post("/stage2/assign", data={"reviews_per_problem": "2"}, follow_redirects=False)
    assert response.status_code == 303

    assignment_a = (
        teacher_root
        / "stage2-review-assignment/review-packages"
        / teacher_package_name("2026000001", STAGE2, "review-assignment")
    )
    assignment_b = (
        teacher_root
        / "stage2-review-assignment/review-packages"
        / teacher_package_name("2026000002", STAGE2, "review-assignment")
    )

    student_a_root = tmp_path / "student-a"
    student_a = TestClient(create_student_app(student_a_root))
    student_a.post("/student-info", data={"student_number": "2026000001", "name": "Alice", "class_id": "A"})
    response = _upload_response(student_a, "/stage2/import", assignment_b)
    assert response.status_code == 303
    assert "notice=" in response.headers["location"]
    assert load_student_state(student_a_root)["student"]["student_number"] == "2026000002"

    _upload(student_a, "/stage2/import", assignment_a)
    assert load_student_state(student_a_root)["student"]["student_number"] == "2026000001"
    assignment_state = load_student_state(student_a_root)["assignment"]
    response = student_a.post(
        "/stage2/package",
        data=_review_form_for_assignment(assignment_state),
        follow_redirects=False,
    )
    assert response.status_code == 303
    review_archive = student_a_root / "stage2-review/exports" / student_package_name("2026000001", STAGE2, KIND_REVIEWS)
    _upload(teacher, "/stage2/reviews/upload", review_archive)
    response = teacher.post("/stage3/feedback", follow_redirects=False)
    assert response.status_code == 303

    feedback_b = (
        teacher_root
        / "stage3-revisions/feedback-packages"
        / teacher_package_name("2026000002", STAGE3, "review-feedback")
    )
    response = _upload_response(student_a, "/stage3/import", feedback_b)
    assert response.status_code == 303
    assert "notice=" in response.headers["location"]
    assert load_student_state(student_a_root)["student"]["student_number"] == "2026000002"

    response = _upload_response(teacher, "/stage1/upload", assignment_a)
    assert response.status_code == 303
    assert "error=" in response.headers["location"]


def test_student_rejects_incomplete_stage2_review_assignment(tmp_path):
    student_root = tmp_path / "student"
    student = TestClient(create_student_app(student_root))
    student.post("/student-info", data={"student_number": "2026000001", "name": "Alice", "class_id": "A"})
    assignment = _make_incomplete_review_assignment_package(tmp_path, "2026000001")

    response = _upload_response(student, "/stage2/import", assignment)
    assert response.status_code == 303
    detail = student.get(response.headers["location"])
    assert "导入审稿任务包失败" in detail.text
    assert "missing reference_solution" in detail.text
    assert load_student_state(student_root)["assignment"] is None


def test_student_stage2_page_discards_legacy_incomplete_assignment(tmp_path):
    student_root = tmp_path / "student"
    ensure_student_tree(student_root)
    state = load_student_state(student_root)
    state["student"] = {"student_number": "2026000001", "name": "Alice", "class_id": "A"}
    state["assignment"] = {
        "assignment_id": "legacy",
        "assigned_problems": [
            {
                "anonymous_id": "anon_legacy",
                "title": "Legacy problem",
                "statement": "Return x.",
                "signature": "def solve(x: int) -> int:",
                "public_tests": [
                    "{\"input\":{\"kwargs\":{\"x\":1}},\"expected\":1}",
                    "{\"input\":{\"kwargs\":{\"x\":2}},\"expected\":2}",
                ],
            }
        ],
    }
    save_student_state(student_root, state)

    student = TestClient(create_student_app(student_root))
    detail = student.get("/stage2")

    assert detail.status_code == 200
    assert "已移除旧审稿任务包" in detail.text
    assert "Legacy problem" not in detail.text
    assert "未提供" not in detail.text
    state = load_student_state(student_root)
    assert state["assignment"] is None
    assert state["reviews"] == {}

    valid_assignment = _make_review_assignment_package(tmp_path, "2026000001")
    response = _upload_response(student, "/stage2/import", valid_assignment)
    assert response.status_code == 303
    state = load_student_state(student_root)
    assert state["assignment"]["assignment_id"] == "asg_test"
    assert "stage2_assignment_error" not in state


def test_student_step_reset_buttons_and_routes(tmp_path):
    student_root = tmp_path / "student"
    ensure_student_tree(student_root)
    client = TestClient(create_student_app(student_root))
    state = load_student_state(student_root)
    state["student"] = {"student_number": "2026000001", "name": "Alice", "class_id": "A"}
    state["settings"] = {"base_url": "https://example.test", "models": ["m1"], "api_key_set": True}
    state["problems"] = [{"problem_id": "pb_reset", "title": "Reset me"}]
    state["assignment"] = {"assignment_id": "asg_reset", "assigned_problems": []}
    state["reviews"] = {"anon_reset": {"conclusion": "major", "explanation": "review"}}
    state["stage2_assignment_error"] = "old error"
    state["feedback"] = {
        "reviews_for_author": [
            {
                "review_id": "rev_reset",
                "problem_id": "pb_reset",
                "review": {"conclusion": "major", "explanation": "summary"},
            }
        ]
    }
    state["revision_responses"] = {"rev_reset": {"response": "ok"}}
    save_student_state(student_root, state)
    (student_root / ".env").write_text("API_KEY=sk-local\n", encoding="utf-8")
    _write_marker(student_root, "settings/marker.txt")
    _write_marker(student_root, "stage1-original/exports/stage1.tar.gz")
    _write_marker(student_root, "stage2-review/imports/stage2.tar.gz")
    _write_marker(student_root, "stage3-revision/exports/stage3.tar.gz")

    for path, action in [
        ("/settings", "/settings/reset"),
        ("/stage1", "/stage1/reset"),
        ("/stage2", "/stage2/reset"),
        ("/stage3", "/stage3/reset"),
    ]:
        body = client.get(path).text
        assert f'action="{action}"' in body
        assert "return confirm(" in body

    response = client.post("/settings/reset", follow_redirects=False)
    assert response.status_code == 303
    state = load_student_state(student_root)
    assert state["student"] == {"student_number": "2026000001", "name": "Alice", "class_id": "A"}
    assert not (student_root / ".env").exists()
    assert _empty_dir(student_root / "settings")

    response = client.post("/stage1/reset", follow_redirects=False)
    assert response.status_code == 303
    state = load_student_state(student_root)
    assert state["problems"] == []
    assert _empty_dir(student_root / "stage1-original/exports")

    response = client.post("/stage2/reset", follow_redirects=False)
    assert response.status_code == 303
    state = load_student_state(student_root)
    assert state["assignment"] is None
    assert state["reviews"] == {}
    assert "stage2_assignment_error" not in state
    assert _empty_dir(student_root / "stage2-review/imports")

    response = client.post("/stage3/reset", follow_redirects=False)
    assert response.status_code == 303
    state = load_student_state(student_root)
    assert state["feedback"] is None
    assert state["revision_responses"] == {}
    assert _empty_dir(student_root / "stage3-revision/exports")


def test_teacher_step_reset_buttons_and_routes(tmp_path):
    teacher_root = tmp_path / "teacher"
    ensure_teacher_tree(teacher_root)
    client = TestClient(create_teacher_app(teacher_root))

    for path, action in [
        ("/settings", "/settings/reset"),
        ("/stage1", "/stage1/reset"),
        ("/stage2/assign", "/stage2/assign/reset"),
        ("/stage2/reviews", "/stage2/reviews/reset"),
        ("/stage3/feedback", "/stage3/feedback/reset"),
        ("/stage3/revisions", "/stage3/revisions/reset"),
        ("/eval", "/eval/reset"),
        ("/stats", "/stats/reset"),
        ("/audit", "/audit/reset"),
    ]:
        body = client.get(path).text
        assert f'action="{action}"' in body
        assert "return confirm(" in body

    state = _seed_teacher_reset_state(teacher_root)
    (teacher_root / ".env").write_text("API_KEY=sk-local\n", encoding="utf-8")
    _write_marker(teacher_root, "settings/marker.txt")
    response = client.post("/settings/reset", follow_redirects=False)
    assert response.status_code == 303
    state = load_teacher_state(teacher_root)
    assert state["settings"]["course_name"] == "CodeSetArena v7"
    assert not (teacher_root / ".env").exists()
    assert _empty_dir(teacher_root / "settings")
    assert any(row["event"] == "settings.reset" for row in state["audit"])

    _seed_teacher_reset_state(teacher_root)
    response = client.post("/stats/reset", follow_redirects=False)
    assert response.status_code == 303
    assert _empty_dir(teacher_root / "stats/exports")

    _seed_teacher_reset_state(teacher_root)
    response = client.post("/eval/reset", follow_redirects=False)
    assert response.status_code == 303
    state = load_teacher_state(teacher_root)
    assert state["eval_runs"] == []
    assert _empty_dir(teacher_root / "ta-eval/runs")

    _seed_teacher_reset_state(teacher_root)
    response = client.post("/stage3/revisions/reset", follow_redirects=False)
    assert response.status_code == 303
    state = load_teacher_state(teacher_root)
    assert state["revisions"] == {}
    assert state["eval_runs"] == []
    assert _empty_dir(teacher_root / "stage3-revisions/uploads")

    _seed_teacher_reset_state(teacher_root)
    response = client.post("/stage3/feedback/reset", follow_redirects=False)
    assert response.status_code == 303
    state = load_teacher_state(teacher_root)
    assert state["feedback"] == {}
    assert state["revisions"] == {}
    assert state["eval_runs"] == []
    assert _empty_dir(teacher_root / "stage3-revisions/feedback-packages")

    _seed_teacher_reset_state(teacher_root)
    response = client.post("/stage2/reviews/reset", follow_redirects=False)
    assert response.status_code == 303
    state = load_teacher_state(teacher_root)
    assert state["reviews"] == {}
    assert state["feedback"] == {}
    assert state["revisions"] == {}
    assert _empty_dir(teacher_root / "stage2-review-assignment/imported-reviews")

    _seed_teacher_reset_state(teacher_root)
    response = client.post("/stage2/assign/reset", follow_redirects=False)
    assert response.status_code == 303
    state = load_teacher_state(teacher_root)
    assert state["assignments"] == {}
    assert state["reviews"] == {}
    assert state["feedback"] == {}
    assert _empty_dir(teacher_root / "stage2-review-assignment/review-packages")

    _seed_teacher_reset_state(teacher_root)
    response = client.post("/stage1/reset", follow_redirects=False)
    assert response.status_code == 303
    state = load_teacher_state(teacher_root)
    assert state["submissions"] == {}
    assert state["assignments"] == {}
    assert state["reviews"] == {}
    assert state["feedback"] == {}
    assert state["revisions"] == {}
    assert _empty_dir(teacher_root / "stage1-submissions/uploads")

    _seed_teacher_reset_state(teacher_root)
    response = client.post("/audit/reset", follow_redirects=False)
    assert response.status_code == 303
    assert load_teacher_state(teacher_root)["audit"] == []


def test_teacher_received_package_rows_have_detail_and_delete_actions(tmp_path):
    teacher_root = tmp_path / "teacher"
    ensure_teacher_tree(teacher_root)
    state = load_teacher_state(teacher_root)
    student = {"student_number": "1001", "name": "Alice", "class_id": "A"}
    problem = {"problem_id": "pb_1", "title": "题目一"}
    state["submissions"] = {
        "1001": {
            "student": student,
            "problems": [problem],
            "archive": "1001-student-stage1-problems.tar.gz",
            "received_at": "2026-06-26T00:00:00+00:00",
        }
    }
    state["assignments"] = {"1001": {"anon_1": {"author_student_number": "1001"}}}
    state["reviews"] = {
        "1001": {
            "student": student,
            "reviews": [{"anonymous_id": "anon_1", "review": {"conclusion": "accept"}}],
            "archive": "1001-student-stage2-reviews.tar.gz",
            "received_at": "2026-06-26T00:00:00+00:00",
        }
    }
    state["feedback"] = {"1001": {"reviews": [{"review_id": "rev_1"}]}}
    state["revisions"] = {
        "1001": {
            "student": student,
            "problems": [problem],
            "responses": [{"review_id": "rev_1", "rating": "5"}],
            "archive": "1001-student-stage3-revision.tar.gz",
            "received_at": "2026-06-26T00:00:00+00:00",
        }
    }
    state["eval_runs"] = [{"run_id": "ta_1"}]
    save_teacher_state(teacher_root, state)
    client = TestClient(create_teacher_app(teacher_root))

    stage1 = client.get("/stage1")
    assert '/stage1/submissions/1001"' in stage1.text
    assert 'action="/stage1/submissions/1001/delete"' in stage1.text
    assert client.get("/stage1/submissions/1001").status_code == 200

    stage2 = client.get("/stage2/reviews")
    assert '/stage2/reviews/1001"' in stage2.text
    assert 'action="/stage2/reviews/1001/delete"' in stage2.text
    assert client.get("/stage2/reviews/1001").status_code == 200

    stage3 = client.get("/stage3/revisions")
    assert '/stage3/revisions/1001"' in stage3.text
    assert 'action="/stage3/revisions/1001/delete"' in stage3.text
    assert client.get("/stage3/revisions/1001").status_code == 200

    response = client.post("/stage3/revisions/1001/delete", follow_redirects=False)
    assert response.status_code == 303
    state = load_teacher_state(teacher_root)
    assert "1001" not in state["revisions"]
    assert state["eval_runs"] == []

    response = client.post("/stage2/reviews/1001/delete", follow_redirects=False)
    assert response.status_code == 303
    state = load_teacher_state(teacher_root)
    assert "1001" not in state["reviews"]
    assert state["feedback"] == {}

    response = client.post("/stage1/submissions/1001/delete", follow_redirects=False)
    assert response.status_code == 303
    state = load_teacher_state(teacher_root)
    assert "1001" not in state["submissions"]
    assert state["assignments"] == {}


def _write_marker(root: Path, relative_path: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("marker", encoding="utf-8")


def _empty_dir(path: Path) -> bool:
    return path.exists() and not any(path.iterdir())


def _seed_teacher_reset_state(root: Path) -> dict:
    state = load_teacher_state(root)
    state.update(
        {
            "settings": {
                "course_name": "Reset Course",
                "base_url": "https://example.test",
                "models": ["m1"],
            },
            "submissions": {"1001": {"student": {"student_number": "1001"}, "problems": []}},
            "assignments": {"1001": {"anon_1": {"author_student_number": "1002"}}},
            "reviews": {"1001": {"reviews": [{"anonymous_id": "anon_1"}]}},
            "feedback": {"1002": {"reviews": [{"review_id": "rev_1"}]}},
            "revisions": {"1002": {"problems": [], "responses": []}},
            "eval_runs": [{"run_id": "ta_1"}],
            "audit": [{"event": "seed", "detail": "before reset"}],
        }
    )
    save_teacher_state(root, state)
    for relative_path in [
        "stage1-submissions/uploads/1001.tar.gz",
        "stage1-submissions/imports/1001/payload.json",
        "stage1-submissions/validation-reports/1001.json",
        "stage2-review-assignment/anonymous-corpus/a.json",
        "stage2-review-assignment/assignments/a.json",
        "stage2-review-assignment/review-packages/1001.tar.gz",
        "stage2-review-assignment/imported-reviews/1001.tar.gz",
        "stage3-revisions/uploads/1002.tar.gz",
        "stage3-revisions/imports/1002/payload.json",
        "stage3-revisions/author-responses/1002.json",
        "stage3-revisions/feedback-packages/1002.tar.gz",
        "ta-eval/runs/eval.tar.gz",
        "stats/exports/stats.json",
        "audit/audit.json",
    ]:
        _write_marker(root, relative_path)
    return state


def _prepare_student_with_five_problems(
    client: TestClient, root: Path, student_number: str, name: str
) -> None:
    _configure_student_model_settings(client)
    client.post("/student-info", data={"student_number": student_number, "name": name, "class_id": "A"})
    for _ in range(PROBLEMS_PER_STUDENT):
        _create_valid_selected_problem(client, root)
    _select_stage1_problem_package(client, root)


def _valid_problem_data() -> dict[str, str]:
    data = {
        "signature": "def solve(x: int) -> int:",
        "statement": "Return x.",
        "reference_solution": "def solve(x: int) -> int:\n    return x\n",
        "notes": "",
        "model": "deepseek-v4-flash",
    }
    for index in range(PUBLIC_TESTS_PER_PROBLEM):
        value = index + 1
        data[f"public_kwargs_{index}"] = json.dumps({"x": value}, separators=(",", ":"))
        data[f"public_expected_{index}"] = json.dumps(value)
    for index in range(AUTHOR_TESTS_PER_PROBLEM):
        data[f"author_kwargs_{index}"] = json.dumps({"x": index}, separators=(",", ":"))
        data[f"author_expected_{index}"] = json.dumps(index)
    return data


def _create_valid_selected_problem(client: TestClient, root: Path | None) -> str:
    _configure_student_model_settings(client)
    response = client.post("/stage1/problems", follow_redirects=False)
    assert response.status_code == 303
    detail_path = response.headers["location"].split("?", 1)[0]
    data = _valid_problem_data()
    response = client.post(f"{detail_path}/validate", data=data, follow_redirects=False)
    assert response.status_code == 303
    response = client.post(f"{detail_path}/run", data=data, follow_redirects=False)
    assert response.status_code == 303
    if root is None:
        return detail_path
    state = load_student_state(root)
    problem = next(item for item in state["problems"] if detail_path.endswith(item["problem_id"]))
    run_id = problem["run_records"][0]["run_id"]
    response = client.post(
        f"{detail_path}/runs/package-selection",
        data={"package_run_ids": run_id},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return detail_path


def _configure_student_model_settings(client: TestClient) -> None:
    response = client.post(
        "/settings",
        data={
            "base_url": "https://api.example.test",
            "api_key": "sk-student-secret",
            "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def _select_stage1_problem_package(client: TestClient, root: Path) -> None:
    state = load_student_state(root)
    problem_ids = [problem["problem_id"] for problem in state["problems"][:PROBLEMS_PER_STUDENT]]
    response = client.post(
        "/stage1/problems/package-selection",
        data={"package_problem_ids": problem_ids},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert f"已选择 {PROBLEMS_PER_STUDENT} 道题目用于 Stage 1 打包" in client.get(response.headers["location"]).text


def _upload(client: TestClient, path: str, archive: Path) -> None:
    response = _upload_response(client, path, archive)
    assert response.status_code == 303, response.text


def _upload_response(client: TestClient, path: str, archive: Path):
    with archive.open("rb") as handle:
        return client.post(
            path,
            files={"file": (archive.name, handle, "application/gzip")},
            follow_redirects=False,
        )


def _make_review_assignment_package(root: Path, student_number: str) -> Path:
    output = root / teacher_package_name(student_number, STAGE2, "review-assignment")
    public_tests = [
        json.dumps({"input": {"kwargs": {"x": value + 1}}, "expected": value + 1}, separators=(",", ":"))
        for value in range(PUBLIC_TESTS_PER_PROBLEM)
    ]
    author_tests = [
        json.dumps({"input": {"kwargs": {"x": value}}, "expected": value}, separators=(",", ":"))
        for value in range(AUTHOR_TESTS_PER_PROBLEM)
    ]
    prompt = render_official_prompt("Return x.", "def solve(x: int) -> int:", public_tests)
    write_package(
        output,
        role=ROLE_TEACHER,
        stage=STAGE2,
        kind="review-assignment",
        student_number=student_number,
        payload={
            "assignment_id": "asg_test",
            "student": {"student_number": student_number, "name": "Alice", "class_id": "A"},
            "assigned_problems": [
                {
                    "anonymous_id": "anon_test",
                    "title": "Return x.",
                    "statement": "Return x.",
                    "signature": "def solve(x: int) -> int:",
                    "reference_solution": "def solve(x: int) -> int:\n    return x\n",
                    "public_tests": public_tests,
                    "author_tests": author_tests,
                    "notes": "",
                    "run_records": [
                        {
                            "run_id": "run_test",
                            "run_origin": "student_self_test",
                            "model": "deepseek-v4-flash",
                            "verdict": "passed",
                            "package_selected": True,
                            "prompt": prompt,
                            "api_request_raw": {"body": {"messages": [{"content": prompt}]}},
                            "api_response_raw": {
                                "choices": [{"message": {"content": "def solve(x: int) -> int:\n    return x\n"}}]
                            },
                            "raw_response": "def solve(x: int) -> int:\n    return x\n",
                            "extracted_code": "def solve(x: int) -> int:\n    return x\n",
                            "test_results": [],
                        }
                    ],
                }
            ],
        },
    )
    return output


def _make_incomplete_review_assignment_package(root: Path, student_number: str) -> Path:
    output = root / teacher_package_name(student_number, STAGE2, "review-assignment")
    write_package(
        output,
        role=ROLE_TEACHER,
        stage=STAGE2,
        kind="review-assignment",
        student_number=student_number,
        payload={
            "assignment_id": "asg_old",
            "student": {"student_number": student_number, "name": "Alice", "class_id": "A"},
            "assigned_problems": [
                {
                    "anonymous_id": "anon_old",
                    "title": "Old assignment",
                    "statement": "Return x.",
                    "signature": "def solve(x: int) -> int:",
                    "public_tests": [],
                }
            ],
        },
    )
    return output


def _make_review_feedback_package(
    root: Path, student_number: str, problem_id: str = "pb_test", review_count: int = 1
) -> Path:
    output = root / teacher_package_name(student_number, STAGE3, "review-feedback")
    reviews = [
        {
            "review_id": f"rev_test_{index}",
            "reviewer_student_number": "2026000002",
            "problem_id": problem_id,
            "anonymous_id": "anon_test",
            "review": {"conclusion": "major", "explanation": f"建议补充边界条件 {index}"},
        }
        for index in range(review_count)
    ]
    write_package(
        output,
        role=ROLE_TEACHER,
        stage=STAGE3,
        kind="review-feedback",
        student_number=student_number,
        payload={
            "student": {"student_number": student_number, "name": "Alice", "class_id": "A"},
            "reviews_for_author": reviews,
        },
    )
    return output


def _assert_controls_are_guided(html: str) -> None:
    controls = _form_controls(html)
    assert controls, "页面应至少包含一个表单控件"
    guided_count = html.count("help-icon")
    assert guided_count >= len(controls), f"help-icon 数量不足：{guided_count} < {len(controls)}"
    for tag_name, attrs in controls:
        if tag_name == "textarea":
            assert "maxlength" in attrs, f"textarea {attrs.get('name')} 缺少 maxlength"
        elif tag_name == "input":
            input_type = attrs.get("type", "text").lower()
            if input_type in {"text", "url", "search", "email", "password"}:
                assert "maxlength" in attrs, f"input {attrs.get('name')} 缺少 maxlength"
            if input_type == "file":
                assert "accept" in attrs, f"file input {attrs.get('name')} 缺少 accept 限制"


def _form_controls(html: str) -> list[tuple[str, dict[str, str]]]:
    controls = []
    seen_names = set()
    for tag_name in ["input", "textarea", "select"]:
        for tag in re.findall(rf"<{tag_name}\b[^>]*>", html):
            attrs = {
                match.group(1): match.group(3)
                for match in re.finditer(r"([\w-]+)=(['\"])(.*?)\2", tag)
            }
            if tag_name == "input" and attrs.get("type", "").lower() in {"hidden", "checkbox", "radio"}:
                continue
            if "name" in attrs:
                if attrs["name"] in seen_names:
                    continue
                seen_names.add(attrs["name"])
                controls.append((tag_name, attrs))
    return controls


def _review_form_for_assignment(assignment: dict) -> dict[str, str]:
    form: dict[str, str] = {}
    for item in assignment.get("assigned_problems", []):
        anon_id = item["anonymous_id"]
        form[f"conclusion_{anon_id}"] = "major"
        form[f"explanation_{anon_id}"] = "边界条件不清楚，示例无法覆盖空输入，建议补充约束与测试。"
        form[f"quality_score_{anon_id}"] = "4"
    return form


def _response_form_for_feedback(feedback: dict) -> dict[str, str]:
    form: dict[str, str] = {}
    for item in feedback.get("reviews_for_author", []):
        review_id = item["review_id"]
        form[f"rating_{review_id}"] = "5"
        form[f"response_{review_id}"] = "已补充边界条件"
    return form


def _tar_names(path: Path) -> set[str]:
    with tarfile.open(path, "r:gz") as tar:
        return {member.name for member in tar.getmembers()}


def _read_bundle_manifest(path: Path) -> dict:
    with tarfile.open(path, "r:gz") as tar:
        manifest = tar.extractfile("bundle-manifest.json")
        assert manifest is not None
        return json.loads(manifest.read().decode("utf-8"))


def _make_stage1_package(root: Path, student_number: str, name: str) -> Path:
    output = root / student_package_name(student_number, STAGE1, KIND_PROBLEMS)
    problems = [_sample_problem(index) for index in range(PROBLEMS_PER_STUDENT)]
    write_package(
        output,
        role=ROLE_STUDENT,
        stage=STAGE1,
        kind=KIND_PROBLEMS,
        student_number=student_number,
        payload={
            "student": {"student_number": student_number, "name": name, "class_id": "A"},
            "problems": problems,
        },
    )
    return output


def _sample_problem(index: int) -> dict:
    public_tests = [
        json.dumps({"input": {"kwargs": {"x": value + 1}}, "expected": value + 1}, separators=(",", ":"))
        for value in range(PUBLIC_TESTS_PER_PROBLEM)
    ]
    prompt = render_official_prompt("Return x.", "def solve(x: int) -> int:", public_tests)
    return {
        "problem_id": f"pb_{index}",
        "title": f"Problem {index}",
        "statement": "Return x.",
        "signature": "def solve(x: int) -> int:",
        "reference_solution": "def solve(x: int) -> int:\n    return x\n",
        "public_tests": public_tests,
        "author_tests": [
            json.dumps({"input": {"kwargs": {"x": value}}, "expected": value}, separators=(",", ":"))
            for value in range(AUTHOR_TESTS_PER_PROBLEM)
        ],
        "failure_hypothesis": "edge case",
        "notes": "",
        "run_analysis": "",
        "run_records": [
            {
                "run_id": f"run_{index}",
                "run_origin": "student_self_test",
                "model": "deepseek-v4-flash",
                "verdict": "passed",
                "created_at": "2026-06-23T00:00:00+00:00",
                "package_selected": True,
                "prompt": prompt,
                "api_request_raw": {"body": {"messages": [{"content": prompt}]}},
                "api_response_raw": {
                    "choices": [{"message": {"content": "def solve(x: int) -> int:\n    return x\n"}}]
                },
                "raw_response": "def solve(x: int) -> int:\n    return x\n",
                "extracted_code": "def solve(x: int) -> int:\n    return x\n",
                "test_results": [
                    {
                        "case_id": "p-0",
                        "test_set": "public",
                        "verdict": "passed",
                        "expected": 1,
                        "actual": 1,
                    }
                ],
            }
        ],
    }
