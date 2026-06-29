#!/usr/bin/env python3
"""Generate mock Stage 1 student packages from the current local problem pool."""

from __future__ import annotations

import argparse
import ast
import copy
import json
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

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
from codesetarena.model_client import real_completion  # noqa: E402
from codesetarena.package_names import student_package_name  # noqa: E402
from codesetarena.packages import read_package, write_package  # noqa: E402
from codesetarena.prompting import prompt_template_id, render_official_prompt, render_official_prompt_parts  # noqa: E402
from codesetarena.run_engine import RunEngineError, execute_problem  # noqa: E402
from codesetarena.storage import load_student_state  # noqa: E402
from codesetarena.student_app import _normalize_state_for_form, _problem_signature_hash  # noqa: E402
from codesetarena.versioning import snapshot_version  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-data-dir", type=Path, default=ROOT / ".codesetarena-student")
    parser.add_argument("--output-dir", type=Path, default=ROOT.parents[1] / "v7/mock/student-stage1")
    parser.add_argument("--model", default="qwen-coder-turbo")
    parser.add_argument("--start-student-number", type=int, default=1001)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--force", action="store_true", help="Ignore existing per-problem checkpoint records.")
    args = parser.parse_args()

    source_root = args.source_data_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    runs_path = output_dir / f"{args.model}-runs.jsonl"
    report_path = output_dir / "generation-report.json"

    state = load_student_state(source_root)
    _normalize_state_for_form(state)
    problems = list(state.get("problems", []))
    if not problems:
        raise SystemExit("No problems found in source data dir.")

    runtime = load_runtime_config(source_root)
    if not runtime.api_key:
        raise SystemExit("API_KEY is required for qwen-coder-turbo generation.")
    config = RuntimeConfig(
        base_url=runtime.base_url,
        api_key=runtime.api_key,
        models=[args.model],
        env_file=runtime.env_file,
    )

    existing = {} if args.force else _load_checkpoint(runs_path)
    run_records: dict[str, dict[str, Any]] = {}
    total = len(problems)
    for index, problem in enumerate(problems, start=1):
        problem_id = str(problem.get("problem_id", ""))
        if problem_id in existing:
            run_records[problem_id] = existing[problem_id]
            print(f"[{index}/{total}] reuse {problem_id}")
            continue
        print(f"[{index}/{total}] request {problem_id} with {args.model}", flush=True)
        run_record = _build_real_run_record(problem, config=config, model=args.model, timeout=args.timeout)
        run_records[problem_id] = run_record
        _append_checkpoint(runs_path, problem_id, run_record)
        print(f"[{index}/{total}] done {problem_id}: {run_record['verdict']}", flush=True)

    archives = _write_student_packages(
        output_dir=output_dir,
        problems=problems,
        run_records=run_records,
        start_student_number=args.start_student_number,
    )
    report = _write_report(
        report_path=report_path,
        source_root=source_root,
        output_dir=output_dir,
        model=args.model,
        problems=problems,
        run_records=run_records,
        archives=archives,
        runtime=runtime,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _build_real_run_record(
    problem: dict[str, Any], *, config: RuntimeConfig, model: str, timeout: float
) -> dict[str, Any]:
    prompt = render_official_prompt(
        str(problem.get("statement", "")),
        str(problem.get("signature", "")),
        problem.get("public_tests", []),
    )
    prompt_parts = render_official_prompt_parts(
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
        "prompt_parts": prompt_parts,
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


def _execute_model_code(problem: dict[str, Any], extracted_code: str) -> dict[str, Any]:
    executable_problem = {**problem, "reference_solution": extracted_code}
    try:
        return execute_problem(executable_problem)
    except RunEngineError as exc:
        return {
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


def _extract_function_code(raw_response: str, signature: str) -> str:
    content = raw_response.strip()
    fenced = re.search(r"```(?:python)?\s*(.*?)```", content, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        content = fenced.group(1).strip()
    expected_name = _function_name_from_signature(signature)
    match = re.search(rf"(^|\n)(def\s+{re.escape(expected_name)}\s*\()", content)
    if match:
        content = content[match.start(2) :].strip()
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return content
    lines = content.splitlines()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == expected_name and node.end_lineno:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno]).strip()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.end_lineno:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno]).strip()
    return content


def _function_name_from_signature(signature: str) -> str:
    source = signature.strip()
    if source.endswith(":"):
        source += "\n    pass"
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "solve"
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            return node.name
    return "solve"


def _write_student_packages(
    *,
    output_dir: Path,
    problems: list[dict[str, Any]],
    run_records: dict[str, dict[str, Any]],
    start_student_number: int,
) -> list[dict[str, Any]]:
    archives = []
    for group_index, offset in enumerate(range(0, len(problems), 5)):
        group = problems[offset : offset + 5]
        if len(group) != 5:
            raise ValueError(f"Problem count must be divisible by 5; leftover={len(group)}")
        student_number = str(start_student_number + group_index)
        packaged_problems = []
        for problem in group:
            problem_id = str(problem.get("problem_id", ""))
            packaged = copy.deepcopy(problem)
            packaged["stage1_package_selected"] = True
            run = copy.deepcopy(run_records[problem_id])
            run["package_selected"] = True
            packaged["run_records"] = [run]
            packaged_problems.append(packaged)
        output = output_dir / student_package_name(student_number, STAGE1, KIND_PROBLEMS)
        payload = {
            "student": {
                "student_number": student_number,
                "name": f"Mock Student {student_number}",
                "class_id": "mock-student-stage1",
            },
            "problems": packaged_problems,
        }
        write_package(
            output,
            role=ROLE_STUDENT,
            stage=STAGE1,
            kind=KIND_PROBLEMS,
            student_number=student_number,
            payload=payload,
        )
        manifest, read_payload = read_package(output)
        archives.append(
            {
                "student_number": student_number,
                "archive": str(output),
                "filename": output.name,
                "problem_ids": [str(problem.get("problem_id", "")) for problem in group],
                "payload_sha256": manifest["payload_sha256"],
                "problem_count": len(read_payload.get("problems", [])),
            }
        )
    return archives


def _write_report(
    *,
    report_path: Path,
    source_root: Path,
    output_dir: Path,
    model: str,
    problems: list[dict[str, Any]],
    run_records: dict[str, dict[str, Any]],
    archives: list[dict[str, Any]],
    runtime: RuntimeConfig,
) -> dict[str, Any]:
    verdict_counts: dict[str, int] = {}
    for run in run_records.values():
        verdict = str(run.get("verdict", "unknown"))
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
    report = {
        "schema_version": "codesetarena.mock_student_stage1_generation.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "source_data_dir": str(source_root),
        "output_dir": str(output_dir),
        "model": model,
        "base_url": runtime.base_url,
        "env_file": str(runtime.env_file) if runtime.env_file else "",
        "problem_count": len(problems),
        "archive_count": len(archives),
        "verdict_counts": verdict_counts,
        "archives": archives,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _load_checkpoint(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    records = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        records[str(item["problem_id"])] = item["run_record"]
    return records


def _append_checkpoint(path: Path, problem_id: str, run_record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"problem_id": problem_id, "run_record": run_record}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
