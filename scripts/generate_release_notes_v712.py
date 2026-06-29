"""Generate tester-facing release notes for CodeSetArena v7.1.2."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


VERSION = "v7.1.2"
REPO_ROOT = Path(__file__).resolve().parents[1]
MD_DIR = REPO_ROOT / "output" / "release-notes"
PDF_DIR = REPO_ROOT / "output" / "pdf"
FONT_NAME = "CodeSetArenaCJK"
FONT_PATH = Path("/System/Library/Fonts/STHeiti Medium.ttc")

NOTES = [
    (
        "助教端设置",
        [
            "设置页新增随机种子，默认 42。相同学生包、审稿份数和随机种子应生成完全一致的审稿分配。",
            "随机种子只接受 0 到 999999999 之间的整数，非法输入应显示中文错误提示。",
        ],
    ),
    (
        "Stage 2 审稿分配",
        [
            "审稿分配改为基于随机种子的伪随机分配，每道题固定包含 AI 和若干学生审稿人，学生审稿人不能是题目作者本人。",
            "审稿任务包内题目顺序也会按随机种子打乱；同一种子重复生成应保持稳定。",
            "页面新增匿名用户映射表和匿名题目映射表，助教可核对匿名 ID 和真实学号/题目 ID。",
            "批量包 teacher-stage2-review-assignments.tar.gz 新增 bundle-manifest.json，记录分配参数、匿名映射、子包文件和分配摘要。",
            "兼容旧版 teacher-state.json：如果本地已有数据缺少 v7.1.2 新增的匿名映射 manifest 字段，Stage 2 审稿分配页应自动补齐默认字段，不再出现 500 错误。",
        ],
    ),
    (
        "Stage 3 发修订反馈",
        [
            "每道题下的审稿意见顺序也按随机种子伪随机排列，AI 审稿不固定排在第一或最后。",
            "批量包 teacher-stage3-review-feedbacks.tar.gz 新增 bundle-manifest.json，记录反馈包列表、随机种子和匿名映射。",
        ],
    ),
    (
        "收包详情页",
        [
            "Stage 1 收包验证、Stage 2 收审稿包、Stage 3 收修订包的每行已有详情和删除入口。",
            "详情页改为友好分块展示，包含题目、测试数据、运行记录、审稿意见和回应信息；页面底部保留原始 JSON。",
            "助教端详情页中涉及匿名 ID 的位置，会同时显示对应真实学号或真实题目 ID，便于人工核查。",
        ],
    ),
    (
        "正式评测",
        [
            "正式评测列表删除助教手动评分列。",
            "作者评分均值改为和题目质量评分一致的格式，例如 5/4/5/3 = 4.2。",
            "作者评分均值按该题审稿意见顺序展示，避免因旧实现的无序遍历导致 x/y/z/w 顺序不稳定。",
        ],
    ),
    (
        "交付包",
        [
            "版本号、Docker 镜像 tag、compose、README、安装手册和 CLI 手册统一升级为 v7.1.2。",
            "本版本仍提供 linux/amd64 和 linux/arm64 两种架构的学生端与助教端本地交付包；学生端无功能变更，仅随版本重打包。",
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
        "本日志汇总自 v7.1.1 打包以来需要重点验证的新功能和交付变化。",
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
        Paragraph("本日志汇总自 v7.1.1 打包以来需要重点验证的新功能和交付变化。", styles["body"]),
        Spacer(1, 8),
    ]
    for title, items in NOTES:
        story.append(Paragraph(title, styles["h2"]))
        for item in items:
            story.append(Paragraph("• " + item, styles["body"]))
    SimpleDocTemplate(str(path), pagesize=A4, title=f"CodeSetArena {VERSION} 测试人员更新日志").build(story)


if __name__ == "__main__":
    main()
