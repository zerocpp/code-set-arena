#!/usr/bin/env python3
"""Complete existing mock Stage 1 student packages for the current v7 rules."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from generate_mock_student_stage1_packages import _execute_model_code, _extract_function_code  # noqa: E402

from codesetarena.config import RuntimeConfig, load_runtime_config  # noqa: E402
from codesetarena.constants import (  # noqa: E402
    EXECUTION_PYTHON_IMAGE,
    EXECUTION_PYTHON_VERSION,
    EXECUTION_TARGET_SECONDS,
    EXECUTION_TIMEOUT_SECONDS,
    KIND_PROBLEMS,
    MODEL_RUN_TEMPERATURE,
    MODEL_RUN_TOP_P,
    ROLE_STUDENT,
    RUN_ORIGIN_STUDENT_SELF_TEST,
    STAGE1,
)
from codesetarena.course_validation import validate_stage1_problem_package  # noqa: E402
from codesetarena.model_client import real_completion  # noqa: E402
from codesetarena.package_names import student_package_name  # noqa: E402
from codesetarena.packages import read_package, write_package  # noqa: E402
from codesetarena.prompting import prompt_template_id, render_official_prompt, render_official_prompt_parts  # noqa: E402
from codesetarena.run_engine import RunEngineError, execute_problem  # noqa: E402
from codesetarena.student_app import _problem_signature_hash, _run_record_matches_current_prompt  # noqa: E402
from codesetarena.versioning import snapshot_version  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-dir", type=Path, default=ROOT.parents[1] / "v7/mock/student-stage1")
    parser.add_argument("--model", default="qwen-coder-turbo")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    package_dir = args.package_dir.resolve()
    runtime = load_runtime_config(env_file=ROOT.parents[1] / ".env")
    config = RuntimeConfig(
        base_url=runtime.base_url,
        api_key=runtime.api_key,
        models=[args.model],
        env_file=runtime.env_file,
    )
    if not config.api_key:
        raise SystemExit("API_KEY is required")

    report: dict[str, Any] = {
        "schema_version": "codesetarena.mock_student_stage1_completion.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "package_dir": str(package_dir),
        "model": args.model,
        "model_backend": "real",
        "archives": [],
        "summary": {
            "archive_count": 0,
            "problem_count": 0,
            "canonicalized_any_of": 0,
            "new_model_runs": 0,
            "metadata_only_runs": 0,
            "reference_passed": 0,
            "reference_failed": 0,
            "model_passed": 0,
            "model_failed": 0,
        },
    }

    for archive in sorted(package_dir.glob("*-student-stage1-problems.tar.gz")):
        archive_report = _complete_archive(
            archive,
            config=config,
            model=args.model,
            timeout=args.timeout,
            runs_path=package_dir / f"{args.model}-runs.jsonl",
        )
        report["archives"].append(archive_report)
        summary = report["summary"]
        summary["archive_count"] += 1
        summary["problem_count"] += archive_report["problem_count"]
        summary["canonicalized_any_of"] += archive_report["canonicalized_any_of"]
        summary["new_model_runs"] += archive_report["new_model_runs"]
        summary["metadata_only_runs"] += archive_report["metadata_only_runs"]
        summary["reference_passed"] += archive_report["reference_passed"]
        summary["reference_failed"] += archive_report["reference_failed"]
        summary["model_passed"] += archive_report["model_passed"]
        summary["model_failed"] += archive_report["model_failed"]

    report_path = package_dir / "completion-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_generation_report(package_dir, report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


def _complete_archive(
    archive: Path,
    *,
    config: RuntimeConfig,
    model: str,
    timeout: float,
    runs_path: Path,
) -> dict[str, Any]:
    manifest, payload = read_package(archive)
    student_number = str(manifest.get("student_number") or payload.get("student", {}).get("student_number") or "")
    problems = payload.get("problems", [])
    archive_report: dict[str, Any] = {
        "filename": archive.name,
        "student_number": student_number,
        "problem_count": len(problems),
        "canonicalized_any_of": 0,
        "new_model_runs": 0,
        "metadata_only_runs": 0,
        "reference_passed": 0,
        "reference_failed": 0,
        "model_passed": 0,
        "model_failed": 0,
        "problems": [],
    }

    for problem in problems:
        changed_tests = _canonicalize_any_of_tests(problem)
        result = _refresh_validation(problem)
        if result["verdict"] == "passed":
            archive_report["reference_passed"] += 1
        else:
            archive_report["reference_failed"] += 1
        needs_new_run = changed_tests or not problem.get("run_records")
        if not needs_new_run:
            needs_new_run = not all(_run_record_matches_current_prompt(problem, run)[0] for run in problem["run_records"])
        if needs_new_run:
            run = _build_model_run(problem, config=config, model=model, timeout=timeout)
            problem["run_records"] = [run]
            _append_checkpoint(runs_path, str(problem.get("problem_id", "")), run)
            archive_report["new_model_runs"] += 1
        else:
            for run in problem.get("run_records", []):
                _refresh_run_metadata(problem, run)
                archive_report["metadata_only_runs"] += 1
        for run in problem.get("run_records", []):
            run["package_selected"] = True
            if run.get("verdict") == "passed":
                archive_report["model_passed"] += 1
            else:
                archive_report["model_failed"] += 1
        problem["stage1_package_selected"] = True
        archive_report["canonicalized_any_of"] += changed_tests
        archive_report["problems"].append(
            {
                "problem_id": problem.get("problem_id", ""),
                "title": problem.get("title", ""),
                "canonicalized_any_of": changed_tests,
                "reference_verdict": result["verdict"],
                "model_verdict": problem.get("run_records", [{}])[0].get("verdict", ""),
            }
        )

    validate_stage1_problem_package(problems)
    output = archive.parent / student_package_name(student_number, STAGE1, KIND_PROBLEMS)
    write_package(
        output,
        role=ROLE_STUDENT,
        stage=STAGE1,
        kind=KIND_PROBLEMS,
        student_number=student_number,
        payload=payload,
    )
    return archive_report


def _canonicalize_any_of_tests(problem: dict[str, Any]) -> int:
    changed = 0
    for field in ["public_tests", "author_tests"]:
        tests = []
        for raw in problem.get(field, []):
            parsed = _parse_test(raw)
            expected = parsed.get("expected")
            if isinstance(expected, dict) and "any_of" in expected:
                parsed["expected"] = _reference_output(problem, parsed)
                changed += 1
            tests.append(json.dumps(parsed, ensure_ascii=False, separators=(",", ":")))
        problem[field] = tests
    return changed


def _refresh_validation(problem: dict[str, Any]) -> dict[str, Any]:
    try:
        result = execute_problem(problem)
    except RunEngineError as exc:
        result = {
            "verdict": "failed",
            "test_results": [
                {
                    "case_id": "execution",
                    "test_set": "system",
                    "index": 0,
                    "expected": None,
                    "actual": None,
                    "verdict": "error",
                    "error_type": exc.error_type,
                    "error": str(exc),
                    "traceback": "",
                }
            ],
        }
    problem["validation"] = {
        "status": "passed" if result["verdict"] == "passed" else "failed",
        "message": "校验通过" if result["verdict"] == "passed" else "参考答案执行未通过",
        "content_hash": _problem_signature_hash(problem),
        "snapshot_version": snapshot_version(),
        "validated_at": datetime.now(UTC).isoformat(),
        "test_results": result["test_results"],
        "execution_python_version": EXECUTION_PYTHON_VERSION,
        "execution_python_image": EXECUTION_PYTHON_IMAGE,
        "execution_target_seconds": EXECUTION_TARGET_SECONDS,
        "execution_timeout_seconds": EXECUTION_TIMEOUT_SECONDS,
    }
    return result


def _build_model_run(
    problem: dict[str, Any],
    *,
    config: RuntimeConfig,
    model: str,
    timeout: float,
) -> dict[str, Any]:
    prompt = render_official_prompt(
        str(problem.get("statement", "")),
        str(problem.get("signature", "")),
        problem.get("public_tests", []),
    )
    created_at = datetime.now(UTC).isoformat()
    run_id = "run_qwen_" + uuid.uuid4().hex[:12]
    completion = real_completion(config=config, model=model, prompt=prompt, timeout=timeout)
    raw_response = completion.content
    extracted_code = _extract_function_code(raw_response, str(problem.get("signature", "")))
    result = _execute_model_code(problem, extracted_code)
    return {
        "run_id": run_id,
        "run_origin": RUN_ORIGIN_STUDENT_SELF_TEST,
        "model": model,
        "base_url": config.base_url,
        "prompt_template_id": prompt_template_id(),
        "prompt": prompt,
        "prompt_parts": render_official_prompt_parts(
            str(problem.get("statement", "")),
            str(problem.get("signature", "")),
            problem.get("public_tests", []),
        ),
        "content_hash": _problem_signature_hash(problem),
        "snapshot_version": snapshot_version(),
        "temperature": MODEL_RUN_TEMPERATURE,
        "top_p": MODEL_RUN_TOP_P,
        "execution_python_version": EXECUTION_PYTHON_VERSION,
        "execution_python_image": EXECUTION_PYTHON_IMAGE,
        "execution_target_seconds": EXECUTION_TARGET_SECONDS,
        "execution_timeout_seconds": EXECUTION_TIMEOUT_SECONDS,
        "verdict": result["verdict"],
        "created_at": created_at,
        "package_selected": True,
        "api_request_raw": completion.request_raw,
        "api_response_raw": completion.response_raw,
        "raw_response": raw_response,
        "extracted_code": extracted_code,
        "test_results": result["test_results"],
    }


def _refresh_run_metadata(problem: dict[str, Any], run: dict[str, Any]) -> None:
    prompt = render_official_prompt(
        str(problem.get("statement", "")),
        str(problem.get("signature", "")),
        problem.get("public_tests", []),
    )
    run["prompt_template_id"] = prompt_template_id()
    run["prompt"] = prompt
    run["prompt_parts"] = render_official_prompt_parts(
        str(problem.get("statement", "")),
        str(problem.get("signature", "")),
        problem.get("public_tests", []),
    )
    run["content_hash"] = _problem_signature_hash(problem)
    run["snapshot_version"] = snapshot_version()
    run["temperature"] = MODEL_RUN_TEMPERATURE
    run["top_p"] = MODEL_RUN_TOP_P
    run["execution_python_version"] = EXECUTION_PYTHON_VERSION
    run["execution_python_image"] = EXECUTION_PYTHON_IMAGE
    run["execution_target_seconds"] = EXECUTION_TARGET_SECONDS
    run["execution_timeout_seconds"] = EXECUTION_TIMEOUT_SECONDS


def _reference_output(problem: dict[str, Any], test: dict[str, Any]) -> Any:
    payload = {
        "reference_solution": problem.get("reference_solution", ""),
        "function_name": _function_name(str(problem.get("signature", ""))),
        "kwargs": test.get("input", {}).get("kwargs", {}),
    }
    completed = subprocess.run(
        [sys.executable, "-c", _REFERENCE_OUTPUT_SCRIPT],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        timeout=EXECUTION_TIMEOUT_SECONDS + 2,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    result = json.loads(completed.stdout)
    if result.get("error"):
        raise RuntimeError(result["error"])
    return result.get("actual")


def _function_name(signature: str) -> str:
    source = signature.strip()
    if source.endswith(":"):
        source += "\n    pass"
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            return node.name
    raise ValueError("signature does not contain a function")


def _parse_test(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        parsed = json.loads(raw)
    else:
        parsed = raw
    if not isinstance(parsed, dict):
        raise ValueError("test must be a JSON object")
    return parsed


def _append_checkpoint(path: Path, problem_id: str, run_record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"problem_id": problem_id, "run_record": run_record}, ensure_ascii=False) + "\n")


def _write_generation_report(package_dir: Path, completion_report: dict[str, Any]) -> None:
    archives = []
    for archive in completion_report["archives"]:
        archives.append(
            {
                "student_number": archive["student_number"],
                "archive": str(package_dir / archive["filename"]),
                "filename": archive["filename"],
                "problem_count": archive["problem_count"],
            }
        )
    report = {
        "schema_version": "codesetarena.mock_student_stage1_generation.v1",
        "created_at": completion_report["created_at"],
        "output_dir": str(package_dir),
        "model": completion_report["model"],
        "model_backend": completion_report["model_backend"],
        "problem_count": completion_report["summary"]["problem_count"],
        "archive_count": completion_report["summary"]["archive_count"],
        "reference_counts": {
            "passed": completion_report["summary"]["reference_passed"],
            "failed": completion_report["summary"]["reference_failed"],
        },
        "model_verdict_counts": {
            "passed": completion_report["summary"]["model_passed"],
            "failed": completion_report["summary"]["model_failed"],
        },
        "archives": archives,
    }
    (package_dir / "generation-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


_REFERENCE_OUTPUT_SCRIPT = r"""
import json
import traceback


def json_safe(value):
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    try:
        json.dumps(value)
    except TypeError:
        return repr(value)
    return value


payload = json.loads(input())
namespace = {}
try:
    exec(compile(payload["reference_solution"], "<reference_solution>", "exec"), namespace)
    actual = namespace[payload["function_name"]](**payload["kwargs"])
    print(json.dumps({"actual": json_safe(actual)}, ensure_ascii=False))
except Exception:
    print(json.dumps({"error": traceback.format_exc(limit=6)}, ensure_ascii=False))
"""


if __name__ == "__main__":
    raise SystemExit(main())
