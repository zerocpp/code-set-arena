"""Generate tester-facing release notes for CodeSetArena v7.1.3."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


VERSION = "v7.1.3"
REPO_ROOT = Path(__file__).resolve().parents[1]
MD_DIR = REPO_ROOT / "output" / "release-notes"
PDF_DIR = REPO_ROOT / "output" / "pdf"
FONT_NAME = "CodeSetArenaCJK"
FONT_PATH = Path("/System/Library/Fonts/STHeiti Medium.ttc")

NOTES = [
    (
        "Stage 2 审稿均衡分配修复",
        [
            "审稿分配仍按助教端设置页的随机种子生成；相同学生包、审稿份数和随机种子应得到完全一致的分配结果。",
            "每道题的审稿人数固定为配置值 x，其中 1 份固定由 AI 完成，x-1 份由学生完成。",
            "学生审稿人不会被分配到自己提交的题目。",
            "学生之间的审稿负载改为全局均衡分配；标准课程数据中，10 名学生、每人 5 题、每题 AI+3 名学生审稿时，每名学生应正好收到 15 道审稿题。",
        ],
    ),
    (
        "需要重点回归的场景",
        [
            "同一种子重复点击生成审稿任务包，分配结果、匿名 ID、包内顺序和 bundle-manifest.json 应保持不变。",
            "更换随机种子后，分配结果或包内顺序应至少有一处变化。",
            "当每题总审稿份数 x 超过可用学生数限制时，系统应给出中文错误提示，不应生成不完整包。",
            "AI 审稿包仍应包含全部学生的全部题目；学生单包仍只包含分配给该学生的匿名题目。",
        ],
    ),
    (
        "交付包与兼容性",
        [
            "版本号、Docker 镜像 tag、compose、README、安装手册和 CLI 手册统一升级为 v7.1.3。",
            "本版本提供 linux/amd64 和 linux/arm64 两种架构的学生端与助教端本地交付包，并提供 SHA256 校验文件；不再单独发布 universal 总包。",
            "学生端功能不变，仅随 v7.1.3 统一重打包，避免版本混用。",
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
        "本日志汇总 v7.1.3 需要重点验证的审稿均衡分配修复和交付变化。",
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
        Paragraph("本日志汇总 v7.1.3 需要重点验证的审稿均衡分配修复和交付变化。", styles["body"]),
        Spacer(1, 8),
    ]
    for title, items in NOTES:
        story.append(Paragraph(title, styles["h2"]))
        for item in items:
            story.append(Paragraph("• " + item, styles["body"]))
    SimpleDocTemplate(str(path), pagesize=A4, title=f"CodeSetArena {VERSION} 测试人员更新日志").build(story)


if __name__ == "__main__":
    main()
