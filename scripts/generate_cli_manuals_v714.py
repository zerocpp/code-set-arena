"""Generate Chinese CLI manuals for CodeSetArena v7.1.4."""

from __future__ import annotations

import shutil
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

VERSION = "v7.1.4"
DATE_TEXT = "资料核对日期：2026-06-24"
REPO_ROOT = Path(__file__).resolve().parents[1]
COURSE_ROOT = REPO_ROOT.parent.parent
PDF_DIR = REPO_ROOT / "output" / "pdf"
V7_DIR = COURSE_ROOT / "v7"
DIST_DIR = REPO_ROOT / "dist"

BLUE = colors.HexColor("#246BFE")
DARK = colors.HexColor("#17202A")
TEXT = colors.HexColor("#20242A")
MUTED = colors.HexColor("#607080")
LINE = colors.HexColor("#DFE4EA")
GREEN = colors.HexColor("#17663A")
AMBER = colors.HexColor("#9B4B00")
RED = colors.HexColor("#B42318")
FONT_NAME = "CodeSetArenaCJK"
FONT_PATH = Path("/System/Library/Fonts/STHeiti Medium.ttc")


def register_fonts() -> None:
    if not FONT_PATH.exists():
        raise FileNotFoundError(f"Chinese font not found: {FONT_PATH}")
    pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName=FONT_NAME,
            fontSize=24,
            leading=31,
            textColor=DARK,
            alignment=TA_CENTER,
            spaceAfter=12,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            parent=base["Normal"],
            fontName=FONT_NAME,
            fontSize=10.5,
            leading=17,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName=FONT_NAME,
            fontSize=17,
            leading=23,
            textColor=DARK,
            spaceBefore=8,
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName=FONT_NAME,
            fontSize=13.2,
            leading=19,
            textColor=DARK,
            spaceBefore=8,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=9.6,
            leading=15.2,
            textColor=TEXT,
            alignment=TA_LEFT,
            spaceAfter=5,
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=8.4,
            leading=12.5,
            textColor=MUTED,
            spaceAfter=3,
        ),
        "cell": ParagraphStyle(
            "cell",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=8.3,
            leading=12,
            textColor=TEXT,
        ),
        "head": ParagraphStyle(
            "head",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=8.5,
            leading=12,
            textColor=colors.white,
        ),
        "code": ParagraphStyle(
            "code",
            parent=base["Code"],
            fontName=FONT_NAME,
            fontSize=7.6,
            leading=10.8,
            textColor=colors.HexColor("#1B2733"),
        ),
    }


S = make_styles()


def p(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, S[style])


def code_block(text: str) -> Table:
    lines = "<br/>".join(escape(line) for line in text.strip().splitlines())
    table = Table([[Paragraph(lines, S["code"])]], colWidths=[17.5 * cm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F6F8FA")),
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def info_box(title: str, body: str, color: colors.Color = BLUE) -> Table:
    table = Table(
        [[p(f"<b>{escape(title)}</b>", "body")], [p(escape(body), "small")]],
        colWidths=[17.5 * cm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.8, color),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def manual_table(headers: list[str], rows: list[list[str]], widths: list[float]) -> Table:
    data = [[Paragraph(escape(item), S["head"]) for item in headers]]
    data.extend([[Paragraph(escape(item), S["cell"]) for item in row] for row in rows])
    table = Table(data, colWidths=[width * cm for width in widths], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.45, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def flow_table(items: list[tuple[str, str]]) -> Table:
    data = []
    for index, (title, body) in enumerate(items, start=1):
        data.append([p(str(index), "body"), p(f"<b>{escape(title)}</b><br/>{escape(body)}", "cell")])
    table = Table(data, colWidths=[1.0 * cm, 16.5 * cm])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.45, LINE),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF1FF")),
                ("TEXTCOLOR", (0, 0), (0, -1), BLUE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def title_page(role: str) -> list:
    return [
        Spacer(1, 2.0 * cm),
        p(f"CodeSetArena {role} CLI 使用手册", "title"),
        p(f"{VERSION} | {DATE_TEXT}", "subtitle"),
        info_box(
            "适用范围",
            "本手册只说明命令行操作。网页端和 Docker 安装步骤请查看同目录下的安装使用手册。",
            GREEN,
        ),
        Spacer(1, 0.5 * cm),
    ]


def student_manual() -> list:
    story = title_page("学生端")
    story.extend(
        [
            p("1. 结论", "h1"),
            p(
                "v7.1.4 可以只通过 CLI 完成学生端 3 个 Stage 的导入和导出。"
                "Stage 3 修订阶段也提供了题目修改、参考答案校验、模型自测、运行记录选择、"
                "审稿回应和最终导出命令。",
            ),
            info_box(
                "工作目录",
                "以下示例使用 .codesetarena-student。实际课程中建议每位学生只维护一个固定目录，"
                "不要在 Stage 之间更换目录。",
            ),
            p("2. 全局准备", "h1"),
            code_block(
                """
code-set-arena student reset --data-dir .codesetarena-student
code-set-arena student settings set \\
  --data-dir .codesetarena-student \\
  --student-number 2026000001 \\
  --name 张三 \\
  --class-id 计科1班
code-set-arena student settings show --data-dir .codesetarena-student
"""
            ),
            p(
                "API Key 默认从环境变量或课程根目录 .env 读取。CLI 输出只显示脱敏状态，不会把真实密钥写入提交包。",
                "small",
            ),
            p("3. Stage 1 原始题目", "h1"),
            flow_table(
                [
                    ("创建或导入题目", "用 create 建立草稿，或用 import 导入已经存在的 Stage 1 包。"),
                    ("更新题目", "用 update 从 JSON 文件写入题面、函数签名、参考答案、样例数据和测试数据。"),
                    ("校验参考答案", "validate 会执行参考答案和 7 个测试用例，失败时返回非零退出码。"),
                    ("模型自测", "run 会使用默认模型或指定模型生成一次运行记录。"),
                    ("选择运行记录", "select-runs 选择 1 到 5 条当前有效且记录完整的运行记录。"),
                    ("选择 5 道题并导出", "select-problems 必须选择 5 道有效题，export 生成提交包。"),
                ]
            ),
            Spacer(1, 0.15 * cm),
            code_block(
                """
code-set-arena student stage1 create \\
  --data-dir .codesetarena-student --sample identity
code-set-arena student stage1 list --data-dir .codesetarena-student
code-set-arena student stage1 update \\
  --data-dir .codesetarena-student \\
  --problem-id pb_cli_01 \\
  --problem-file problem-01.json
code-set-arena student stage1 validate \\
  --data-dir .codesetarena-student --problem-id pb_cli_01
code-set-arena student stage1 run \\
  --data-dir .codesetarena-student --problem-id pb_cli_01
code-set-arena student stage1 select-runs \\
  --data-dir .codesetarena-student \\
  --problem-id pb_cli_01 --run-id run_xxx
code-set-arena student stage1 select-problems \\
  --data-dir .codesetarena-student \\
  --problem-id pb_cli_01 --problem-id pb_cli_02 \\
  --problem-id pb_cli_03 --problem-id pb_cli_04 \\
  --problem-id pb_cli_05
code-set-arena student stage1 export --data-dir .codesetarena-student
"""
            ),
            p(
                "导出文件名：{学号}-student-stage1-problems.tar.gz。"
                "package 和 export 等价，建议学生统一使用 export。",
                "small",
            ),
            PageBreak(),
            p("4. Stage 2 匿名审稿", "h1"),
            p("收到助教发放的审稿任务包后，先导入，再列出匿名题目 ID，然后逐题提交结论和建议。"),
            code_block(
                """
code-set-arena student stage2 import \\
  --data-dir .codesetarena-student \\
  --file 2026000001-teacher-stage2-review-assignment.tar.gz
code-set-arena student stage2 list --data-dir .codesetarena-student
code-set-arena student stage2 review \\
  --data-dir .codesetarena-student \\
  --anonymous-id anon_xxx \\
  --conclusion major \\
  --explanation 建议增加边界用例并说明排序规则
code-set-arena student stage2 export --data-dir .codesetarena-student
"""
            ),
            manual_table(
                ["字段", "允许值或要求"],
                [
                    ["conclusion", "accept, minor, major, reject 之一，不能留空。"],
                    ["explanation", "写明建议或风险点，不能留空。"],
                    ["导出文件名", "{学号}-student-stage2-reviews.tar.gz"],
                ],
                [4.0, 13.5],
            ),
            p("5. Stage 3 修订提交", "h1"),
            p(
                "导入反馈包后，用 list 查看每条 review_id 和对应 problem_id。"
                "如果修改了题目，必须重新 validate、run、select-runs，再选择 5 道题用于最终包。"
            ),
            code_block(
                """
code-set-arena student stage3 import \\
  --data-dir .codesetarena-student \\
  --file 2026000001-teacher-stage3-review-feedback.tar.gz
code-set-arena student stage3 list --data-dir .codesetarena-student
code-set-arena student stage3 update \\
  --data-dir .codesetarena-student \\
  --problem-id pb_cli_01 --problem-file revised-01.json
code-set-arena student stage3 validate \\
  --data-dir .codesetarena-student --problem-id pb_cli_01
code-set-arena student stage3 run \\
  --data-dir .codesetarena-student --problem-id pb_cli_01
code-set-arena student stage3 select-runs \\
  --data-dir .codesetarena-student \\
  --problem-id pb_cli_01 --run-id run_xxx
code-set-arena student stage3 respond \\
  --data-dir .codesetarena-student \\
  --review-id rev_xxx --rating 5 \\
  --response 已补充边界条件和测试数据
code-set-arena student stage3 select-problems \\
  --data-dir .codesetarena-student \\
  --problem-id pb_cli_01 --problem-id pb_cli_02 \\
  --problem-id pb_cli_03 --problem-id pb_cli_04 \\
  --problem-id pb_cli_05
code-set-arena student stage3 export --data-dir .codesetarena-student
"""
            ),
            manual_table(
                ["检查点", "说明"],
                [
                    ["评分", "rating 只能是 1 到 5。5 表示完全采纳，1 表示基本无帮助。"],
                    ["回应", "response 不能为空，说明如何采纳或为什么不采纳。"],
                    ["运行记录", "每道导出的题必须选中 1 到 5 条当前有效运行记录。"],
                    ["导出文件名", "{学号}-student-stage3-revision.tar.gz"],
                ],
                [4.0, 13.5],
            ),
            p("6. 题目 JSON 模板", "h1"),
            code_block(
                """
{
  "title": "绝对值",
  "statement": "给定一个整数，返回它的绝对值。",
  "signature": "def solve(x: int) -> int:",
  "reference_solution": "def solve(x: int) -> int:\\n    return abs(x)\\n",
  "public_tests": [
    {"kwargs": {"x": -1}, "expected": 1},
    {"kwargs": {"x": 2}, "expected": 2}
  ],
  "author_tests": [
    {"kwargs": {"x": 0}, "expected": 0},
    {"kwargs": {"x": -7}, "expected": 7},
    {"kwargs": {"x": 9}, "expected": 9},
    {"kwargs": {"x": -100}, "expected": 100},
    {"kwargs": {"x": 5}, "expected": 5}
  ],
  "notes": "只给人类阅读，不进入模型提示词。"
}
"""
            ),
            p("7. 常见错误", "h1"),
            manual_table(
                ["现象", "处理"],
                [
                    ["提示尚未校验", "先运行 validate。题目变更或系统快照版本变更后，旧校验会失效。"],
                    ["不能选择 run", "该运行记录与当前题目提示词或固定参数不一致，重新 run 后再 select-runs。"],
                    ["不能导出 Stage 3", "确认 5 道题均已选中，且每条审稿意见都有 rating 和 response。"],
                    ["API 请求失败", "检查 .env、BASE_URL、API_KEY、MODELS 和网络。可优先用 mock 或样例流程排查。"],
                ],
                [5.0, 12.5],
            ),
        ]
    )
    return story


def teacher_manual() -> list:
    story = title_page("助教端")
    story.extend(
        [
            p("1. 角色与目录", "h1"),
            p(
                "助教端 CLI 可完成收包验证、审稿分配、收审稿包、发修订反馈、收修订包、正式评测、统计导出和审计查看。"
            ),
            code_block(
                """
code-set-arena teacher reset --data-dir .codesetarena-teacher
code-set-arena teacher settings set \\
  --data-dir .codesetarena-teacher \\
  --course-name CodeSetArena-v7.1
code-set-arena teacher settings show --data-dir .codesetarena-teacher
"""
            ),
            p("2. 助教全流程", "h1"),
            flow_table(
                [
                    ("Stage 1 收包", "逐个上传学生的 {学号}-student-stage1-problems.tar.gz。"),
                    ("Stage 2 分配", "生成每名学生的审稿任务包，同时生成 AI 审稿任务包。"),
                    ("Stage 2 收审稿", "逐个上传学生导出的 Stage 2 审稿包。"),
                    ("Stage 3 发反馈", "按作者生成修订反馈包。"),
                    ("Stage 3 收修订", "上传学生最终修订包并校验回应和题目结构。"),
                    ("正式评测和统计", "运行助教正式评测，导出课程统计和审计记录。"),
                ]
            ),
            p("3. Stage 1 收包验证", "h1"),
            code_block(
                """
code-set-arena teacher stage1 upload \\
  --data-dir .codesetarena-teacher \\
  --file 2026000001-student-stage1-problems.tar.gz
code-set-arena teacher stage1 list --data-dir .codesetarena-teacher
"""
            ),
            manual_table(
                ["验证内容", "说明"],
                [
                    ["文件名", "必须匹配 {学号}-student-stage1-problems.tar.gz。"],
                    ["包结构", "校验 manifest、role、stage、kind、payload 和 hash。"],
                    ["题目数量", "每个学生包必须包含系统常量规定的题目数量，当前为 5 道。"],
                    ["运行证据", "每道题必须有选中的学生自测运行记录，且保留 raw request 和 raw response。"],
                ],
                [4.4, 13.1],
            ),
            p("4. Stage 2 审稿分配", "h1"),
            code_block(
                """
code-set-arena teacher stage2 assign \\
  --data-dir .codesetarena-teacher \\
  --reviews-per-problem 2
"""
            ),
            info_box(
                "reviews-per-problem 的含义",
                "该参数表示每道题总共需要几份审稿意见。其中固定 1 份分配给 AI，"
                "其余 reviews-per-problem - 1 份由学生互审完成。"
                "AI 包文件名为 AI-teacher-stage2-review-assignment.tar.gz。",
                AMBER,
            ),
            manual_table(
                ["产物", "位置或命名"],
                [
                    ["单人任务包", "{学号}-teacher-stage2-review-assignment.tar.gz"],
                    ["AI 任务包", "AI-teacher-stage2-review-assignment.tar.gz，包含全部学生的全部题目。"],
                    ["批量包", "teacher-stage2-review-assignments.tar.gz"],
                ],
                [4.0, 13.5],
            ),
            PageBreak(),
            p("5. Stage 2 收审稿包", "h1"),
            code_block(
                """
code-set-arena teacher stage2 upload-reviews \\
  --data-dir .codesetarena-teacher \\
  --file 2026000001-student-stage2-reviews.tar.gz
"""
            ),
            p("系统会校验学生只审了分配给自己的匿名题目，并且每条 review 都有结论和建议。"),
            p("6. Stage 3 发反馈和收修订", "h1"),
            code_block(
                """
code-set-arena teacher stage3 feedback --data-dir .codesetarena-teacher
code-set-arena teacher stage3 upload-revision \\
  --data-dir .codesetarena-teacher \\
  --file 2026000001-student-stage3-revision.tar.gz
"""
            ),
            manual_table(
                ["步骤", "说明"],
                [
                    ["feedback", "为收到审稿意见的作者生成 {学号}-teacher-stage3-review-feedback.tar.gz。"],
                    ["upload-revision", "校验修订后的完整题目、选中运行记录、全部审稿回应。"],
                    ["缺少反馈", "如果学生没有对应反馈包，修订包会被拒绝。"],
                ],
                [4.0, 13.5],
            ),
            p("7. 正式评测、统计、审计", "h1"),
            code_block(
                """
code-set-arena teacher eval run --data-dir .codesetarena-teacher
code-set-arena teacher stats export --data-dir .codesetarena-teacher
code-set-arena teacher audit list --data-dir .codesetarena-teacher
"""
            ),
            manual_table(
                ["命令", "输出"],
                [
                    ["eval run", "teacher-stage4-official-eval.tar.gz。运行记录标记为 ta_official_eval。"],
                    ["stats export", "teacher-stage4-course-stats.json。包含收包、审稿、修订和评测统计。"],
                    ["audit list", "输出助教端关键操作日志，便于排查课程流程问题。"],
                ],
                [4.0, 13.5],
            ),
            p("8. 完整示例", "h1"),
            code_block(
                """
code-set-arena teacher reset --data-dir .codesetarena-teacher
code-set-arena teacher stage1 upload \\
  --data-dir .codesetarena-teacher \\
  --file 2026000001-student-stage1-problems.tar.gz
code-set-arena teacher stage1 upload \\
  --data-dir .codesetarena-teacher \\
  --file 2026000002-student-stage1-problems.tar.gz
code-set-arena teacher stage2 assign \\
  --data-dir .codesetarena-teacher --reviews-per-problem 2
code-set-arena teacher stage2 upload-reviews \\
  --data-dir .codesetarena-teacher \\
  --file 2026000001-student-stage2-reviews.tar.gz
code-set-arena teacher stage3 feedback --data-dir .codesetarena-teacher
code-set-arena teacher stage3 upload-revision \\
  --data-dir .codesetarena-teacher \\
  --file 2026000002-student-stage3-revision.tar.gz
code-set-arena teacher eval run --data-dir .codesetarena-teacher
code-set-arena teacher stats export --data-dir .codesetarena-teacher
"""
            ),
            p("9. 常见错误", "h1"),
            manual_table(
                ["现象", "处理"],
                [
                    ["上传失败", "先检查文件名是否包含正确学号、角色、stage 和 kind。"],
                    ["不能分配审稿", "至少先上传学生 Stage 1 包；如果需要学生互审，至少需要 2 名学生。"],
                    ["收审稿包失败", "确认该学生的审稿任务包由当前助教端生成，且没有额外匿名题。"],
                    ["收修订包失败", "确认已生成并发放 Stage 3 feedback，学生包中回应和运行记录完整。"],
                ],
                [5.0, 12.5],
            ),
        ]
    )
    return story


def footer(canvas, doc) -> None:  # type: ignore[no-untyped-def]
    canvas.saveState()
    canvas.setFont(FONT_NAME, 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(1.6 * cm, 1.0 * cm, f"CodeSetArena {VERSION}")
    canvas.drawRightString(A4[0] - 1.6 * cm, 1.0 * cm, f"{doc.page}")
    canvas.restoreState()


def build_pdf(filename: str, story: list) -> Path:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    path = PDF_DIR / filename
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=1.6 * cm,
        leftMargin=1.6 * cm,
        topMargin=1.55 * cm,
        bottomMargin=1.45 * cm,
        title=filename,
        author="CodeSetArena",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    for target_dir in [V7_DIR, DIST_DIR]:
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target_dir / filename)
    return path


def main() -> None:
    register_fonts()
    student_path = build_pdf(f"CodeSetArena-学生端-CLI使用手册-{VERSION}.pdf", student_manual())
    teacher_path = build_pdf(f"CodeSetArena-助教端-CLI使用手册-{VERSION}.pdf", teacher_manual())
    print(student_path)
    print(teacher_path)
    print(V7_DIR / student_path.name)
    print(V7_DIR / teacher_path.name)
    print(DIST_DIR / student_path.name)
    print(DIST_DIR / teacher_path.name)


if __name__ == "__main__":
    main()
