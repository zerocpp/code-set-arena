"""Generate tester-facing release notes for CodeSetArena v7.1.4."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


VERSION = "v7.1.4"
REPO_ROOT = Path(__file__).resolve().parents[1]
MD_DIR = REPO_ROOT / "output" / "release-notes"
PDF_DIR = REPO_ROOT / "output" / "pdf"
FONT_NAME = "CodeSetArenaCJK"
FONT_PATH = Path("/System/Library/Fonts/STHeiti Medium.ttc")

NOTES = [
    (
        "模型运行改为真实 API",
        [
            "学生端 Stage 1 和 Stage 3 的“执行模型运行”不再使用本地 mock 返回参考答案，而是调用设置页 Base URL、API Key 和模型名称对应的真实 OpenAI-compatible API。",
            "助教端正式评测同样改为真实 API 调用；模型返回后系统提取函数代码，再使用本地执行器运行 2 条样例数据和 5 条测试数据。",
            "模型名称不再限制为课程 .env 中 MODELS 的子集；学生和助教可以在设置页自主填写模型名。若模型服务不支持该名称，应由真实 API 返回错误。",
            "运行记录继续保存脱敏后的原始请求 raw、原始响应 raw、模型返回文本、提取后的代码和逐用例执行结果；API Key 不写入 state 或提交包。",
        ],
    ),
    (
        "需要重点回归的场景",
        [
            "在设置页填写不存在的模型名，例如 kfcvivo50，点击运行时应看到真实 API 返回的中文错误提示，不应生成可打包运行记录。",
            "真实 API 成功返回时，运行记录中的 provider_api 不应再是 local_mock_openai_chat_completions。",
            "模型返回 Markdown 代码块、解释文字或多个函数时，系统应尽量提取与题目函数签名一致的函数进行判题。",
            "真实 API 超时、HTTP 401/400、网络不可达时，应展示脱敏错误；页面不应滚动到无关位置，API Key 不应出现在页面、state、导出包或日志中。",
            "助教正式评测遇到单题 API 错误时，应计入失败进度，不应把失败请求登记成合法正式评测记录。",
        ],
    ),
    (
        "交付包与兼容性",
        [
            "版本号、Docker 镜像 tag、compose、README、安装手册和 CLI 手册统一升级为 v7.1.4。",
            "本版本提供 linux/amd64 和 linux/arm64 两种架构的学生端与助教端本地交付包，并提供 SHA256 校验文件；不再单独发布 universal 总包。",
            "v7.1.4 延续 v7.1.3 的审稿均衡分配、匿名映射、收包详情页和正式评测页面结构；主要变化集中在模型调用路径。",
        ],
    ),
]


def main() -> None:
    MD_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    md_path = MD_DIR / f"CodeSetArena-{VERSION}-测试人员更新日志.md"
    pdf_path = PDF_DIR / f"CodeSetArena-{VERSION}-测试人员更新日志.pdf"
    md_path.write_text(_markdown(), encoding="utf-8")
    _pdf(pdf_path)
    print(md_path)
    print(pdf_path)


def _markdown() -> str:
    lines = [
        f"# CodeSetArena {VERSION} 测试人员更新日志",
        "",
        "本日志汇总 v7.1.4 需要重点验证的真实 API 调用、错误处理和交付变化。",
        "",
    ]
    for title, items in NOTES:
        lines.extend([f"## {title}", ""])
        lines.extend([f"- {item}" for item in items])
        lines.append("")
    return "\n".join(lines)


def _pdf(path: Path) -> None:
    if not FONT_PATH.exists():
        raise FileNotFoundError(f"Chinese font not found: {FONT_PATH}")
    pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName=FONT_NAME,
            fontSize=22,
            leading=30,
            textColor=colors.HexColor("#17202A"),
            alignment=TA_CENTER,
            spaceAfter=12,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName=FONT_NAME,
            fontSize=15,
            leading=22,
            textColor=colors.HexColor("#17202A"),
            spaceBefore=10,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=10.5,
            leading=17,
            textColor=colors.HexColor("#20242A"),
            alignment=TA_LEFT,
            spaceAfter=5,
        ),
    }
    story = [
        Paragraph(f"CodeSetArena {VERSION} 测试人员更新日志", styles["title"]),
        Paragraph("本日志汇总 v7.1.4 需要重点验证的真实 API 调用、错误处理和交付变化。", styles["body"]),
        Spacer(1, 8),
    ]
    for title, items in NOTES:
        story.append(Paragraph(title, styles["h2"]))
        for item in items:
            story.append(Paragraph("• " + item, styles["body"]))
    SimpleDocTemplate(str(path), pagesize=A4, title=f"CodeSetArena {VERSION} 测试人员更新日志").build(story)


if __name__ == "__main__":
    main()
