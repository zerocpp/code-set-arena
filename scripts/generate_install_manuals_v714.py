"""Generate Chinese Docker installation and operation manuals for v7.1.4."""

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
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

VERSION = "v7.1.4"
DEFAULT_PACKAGE_PLATFORM = "linux-amd64"
DATE_TEXT = "资料核对日期：2026-06-23"
REPO_ROOT = Path(__file__).resolve().parents[1]
COURSE_ROOT = REPO_ROOT.parent.parent
PDF_DIR = REPO_ROOT / "output" / "pdf"
V7_DIR = COURSE_ROOT / "v7"

BLUE = colors.HexColor("#246BFE")
DARK = colors.HexColor("#17202A")
TEXT = colors.HexColor("#20242A")
MUTED = colors.HexColor("#607080")
LINE = colors.HexColor("#DFE4EA")
GREEN = colors.HexColor("#17663A")
AMBER = colors.HexColor("#9B4B00")
FONT_NAME = "CodeSetArenaCJK"
FONT_PATH = Path("/System/Library/Fonts/STHeiti Medium.ttc")


def register_fonts() -> None:
    if not FONT_PATH.exists():
        raise FileNotFoundError(f"Chinese font not found: {FONT_PATH}")
    pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName=FONT_NAME,
            fontSize=24,
            leading=32,
            textColor=DARK,
            alignment=TA_CENTER,
            spaceAfter=14,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            parent=base["Normal"],
            fontName=FONT_NAME,
            fontSize=11,
            leading=18,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=10,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName=FONT_NAME,
            fontSize=18,
            leading=24,
            textColor=DARK,
            spaceBefore=8,
            spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName=FONT_NAME,
            fontSize=14,
            leading=20,
            textColor=DARK,
            spaceBefore=8,
            spaceAfter=8,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=10,
            leading=16,
            textColor=TEXT,
            alignment=TA_LEFT,
            spaceAfter=6,
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=8.6,
            leading=13,
            textColor=MUTED,
            spaceAfter=4,
        ),
        "cell": ParagraphStyle(
            "cell",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=9,
            leading=13,
            textColor=TEXT,
        ),
        "cell_white": ParagraphStyle(
            "cell_white",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=9,
            leading=13,
            textColor=colors.white,
        ),
        "code": ParagraphStyle(
            "code",
            parent=base["Code"],
            fontName=FONT_NAME,
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#1B2733"),
        ),
    }


S = styles()


def p(text: str, style: str = "body") -> Paragraph:
    return Paragraph(escape(text), S[style])


def rich(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, S[style])


def h1(text: str) -> Paragraph:
    return p(text, "h1")


def h2(text: str) -> Paragraph:
    return p(text, "h2")


def code_block(text: str) -> Table:
    block = Preformatted(text.strip(), S["code"])
    table = Table([[block]], colWidths=[16.5 * cm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F5F8")),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def info_box(title: str, body: str, color: colors.Color = BLUE) -> Table:
    table = Table(
        [
            [Paragraph(escape(title), S["cell_white"])],
            [Paragraph(escape(body), S["cell"])],
        ],
        colWidths=[16.5 * cm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), color),
                ("BACKGROUND", (0, 1), (-1, 1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.7, color),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def key_value_table(rows: list[tuple[str, str]]) -> Table:
    data = [[p(k, "cell"), p(v, "cell")] for k, v in rows]
    table = Table(data, colWidths=[4.2 * cm, 12.3 * cm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF4FF")),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def step_table(rows: list[tuple[str, str, str]]) -> Table:
    data = [[p("步骤", "cell_white"), p("操作", "cell_white"), p("完成标志", "cell_white")]]
    data.extend([[p(a, "cell"), p(b, "cell"), p(c, "cell")] for a, b, c in rows])
    table = Table(data, colWidths=[2.1 * cm, 9.0 * cm, 5.4 * cm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), FONT_NAME),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def flow_diagram(steps: list[str], color: colors.Color = BLUE) -> Table:
    cells: list[Paragraph] = []
    widths: list[float] = []
    arrow_width = 0.5 * cm
    box_width = (16.5 * cm - (len(steps) - 1) * arrow_width) / len(steps)
    for index, step in enumerate(steps):
        cells.append(Paragraph(escape(step), S["cell_white"]))
        widths.append(box_width)
        if index != len(steps) - 1:
            cells.append(Paragraph("&gt;", S["cell"]))
            widths.append(arrow_width)
    table = Table([cells], colWidths=widths)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]
    for column in range(0, len(cells), 2):
        style.extend(
            [
                ("BACKGROUND", (column, 0), (column, 0), color),
                ("BOX", (column, 0), (column, 0), 0.5, color),
            ]
        )
    table.setStyle(TableStyle(style))
    return table


def ui_mock(role: str, nav: list[str], cards: list[tuple[str, str]]) -> Table:
    nav_text = "  ".join(nav)
    card_rows = [[p(title, "cell"), p(body, "cell")] for title, body in cards]
    table = Table(
        [
            [
                Paragraph(f"CodeSetArena {escape(role)} <font color='#DCE6F2'>{VERSION}</font>", S["cell_white"]),
                "",
            ],
            [Paragraph(escape(nav_text), S["small"]), ""],
            *card_rows,
        ],
        colWidths=[4.4 * cm, 12.1 * cm],
    )
    table.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 0), (1, 0)),
                ("SPAN", (0, 1), (1, 1)),
                ("BACKGROUND", (0, 0), (-1, 0), DARK),
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#EEF4FF")),
                ("BACKGROUND", (0, 2), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.7, LINE),
                ("INNERGRID", (0, 2), (-1, -1), 0.4, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def platform_install_section() -> list:
    return [
        h1("一、安装 Docker"),
        p("CodeSetArena v7.1.4 以 Docker 镜像形式交付。学生端和助教端是两个独立容器，数据目录也相互独立。"),
        flow_diagram(["解压离线包", "安装 Docker", "载入镜像", "启动容器", "打开网页"], BLUE),
        Spacer(1, 0.22 * cm),
        info_box(
            "离线包优先",
            "课程可发放 codesetarena-docker-offline-v7.1.4.tar.gz。这个包应包含 Docker Desktop 安装包、Windows WSL MSI、Linux 辅助脚本，以及学生端/助教端本地镜像交付包。Windows WSL 2 通常使用 linux-amd64；Apple Silicon 或 ARM64 Linux 使用 linux-arm64。网络较差时，先用这些本地文件安装，不要让每台电脑现场重新下载。",
            BLUE,
        ),
        code_block(
            """
# 解压并校验离线包
tar -xzf codesetarena-docker-offline-v7.1.4.tar.gz
cd docker-offline-v7.1.4
shasum -a 256 -c SHA256SUMS.txt
            """
        ),
        h2("macOS"),
        step_table(
            [
                (
                    "1",
                    "Apple Silicon 机器打开 installers/macos/apple-silicon/Docker.dmg；Intel 机器打开 installers/macos/intel/Docker.dmg。",
                    "DMG 安装器打开。",
                ),
                (
                    "2",
                    "双击 Docker.dmg，将 Docker 拖入 Applications，然后启动 Docker Desktop。",
                    "菜单栏出现 Docker 图标。",
                ),
                (
                    "3",
                    "终端执行 docker version，能看到 Client 和 Server 两段信息。",
                    "Docker daemon 已启动。",
                ),
                (
                    "可选",
                    "已熟悉命令行的用户也可以使用 Colima 等本地 daemon。课程手册默认按 Docker Desktop 讲解。",
                    "docker context 指向可用 daemon。",
                ),
            ]
        ),
        h2("Windows"),
        step_table(
            [
                (
                    "1",
                    "AMD64 机器运行 installers\\windows\\amd64\\Docker Desktop Installer.exe；ARM64 机器运行 installers\\windows\\arm64\\Docker Desktop Installer.exe。",
                    "Docker Desktop 安装器打开。",
                ),
                (
                    "2",
                    "如果提示需要 WSL 2，用管理员 PowerShell 启用 Microsoft-Windows-Subsystem-Linux 和 VirtualMachinePlatform，重启后运行 installers\\windows\\wsl\\*.msi。",
                    "Docker Desktop 可正常打开。",
                ),
                (
                    "3",
                    "PowerShell 执行 docker version 和 docker compose version。",
                    "两个命令都能输出版本。",
                ),
            ]
        ),
        h2("Linux"),
        step_table(
            [
                (
                    "1",
                    "Ubuntu 桌面用户可尝试 installers/linux/ubuntu-amd64/docker-desktop-amd64.deb；服务器或教学机建议安装 Docker Engine。",
                    "选择一种安装方式即可。",
                ),
                (
                    "2",
                    "完全离线时，在同版本同架构的联网 Ubuntu 上运行 installers/linux/ubuntu-engine-debs/collect-ubuntu-engine-debs.sh，拷贝 debs 目录到离线机后运行 install-ubuntu-engine-debs.sh。",
                    "Docker Engine 和 compose plugin 安装完成。",
                ),
                (
                    "3",
                    "如果当前用户不能运行 docker，可加入 docker 组或使用 sudo。加入组后需要重新登录。",
                    "docker ps 可执行。",
                ),
            ]
        ),
        info_box(
            "中国大陆网络提示",
            "助教可在网络较好的机器上运行 scripts/prepare_docker_offline_bundle_v714.py 生成完整离线包。确需本地构建时，可设置 PIP_INDEX_URL 为学校或可信镜像源；Docker Hub 镜像加速请按学校或单位提供的 registry mirror 配置，不建议随意复制未知镜像地址。",
            AMBER,
        ),
        code_block(
            """
# 验证 Docker 已经可用
docker version
docker compose version
docker version --format '{{{{.Server.Os}}}}/{{{{.Server.Arch}}}}'

# Docker Hub 拉取慢时，优先使用课程离线镜像包
docker load -i codesetarena-student-v7.1.4.image.tar
docker load -i codesetarena-teacher-v7.1.4.image.tar
            """
        ),
    ]


def common_troubleshooting(port: int) -> list:
    return [
        h1("常见问题"),
        step_table(
            [
                (
                    "端口占用",
                    f"如果 {port} 端口被占用，修改 docker-compose.yml 中左侧端口，例如 18000:{port}，然后用新端口访问。",
                    "浏览器可打开新地址。",
                ),
                (
                    "Docker 未启动",
                    "报 Cannot connect to the Docker daemon 时，先启动 Docker Desktop 或本地 daemon，再重试 docker version。",
                    "Server 信息出现。",
                ),
                (
                    "镜像拉取失败",
                    "使用助教提供的 local tar.gz 包和 docker load；若必须本地构建，配置可信 registry mirror 和 PIP_INDEX_URL。",
                    "docker images 能看到 v7.1.4 镜像。",
                ),
                (
                    "API 调用失败",
                    "检查设置页 Base URL、模型列表和 API Key。API Key 不会写入提交包；错误会显示在运行结果中。",
                    "模型运行返回可解析结果。",
                ),
                (
                    "页面打不开",
                    "确认容器仍在运行：docker ps。若容器退出，查看 docker logs 容器名。",
                    "日志中没有启动错误。",
                ),
            ]
        ),
    ]


def sources_section() -> list:
    refs = [
        ("Docker Desktop for Mac", "https://docs.docker.com/desktop/setup/install/mac-install/"),
        ("Docker Desktop for Windows", "https://docs.docker.com/desktop/setup/install/windows-install/"),
        ("Docker Desktop for Linux", "https://docs.docker.com/desktop/setup/install/linux/"),
        ("Docker Engine on Ubuntu", "https://docs.docker.com/engine/install/ubuntu/"),
        ("Docker Compose plugin", "https://docs.docker.com/compose/install/linux/"),
        ("docker image load", "https://docs.docker.com/reference/cli/docker/image/load/"),
        ("docker container run", "https://docs.docker.com/reference/cli/docker/container/run/"),
        ("Docker Hub registry mirror", "https://docs.docker.com/docker-hub/image-library/mirror/"),
        ("Microsoft WSL offline install", "https://learn.microsoft.com/en-us/windows/wsl/install"),
        ("Docker Desktop license", "https://docs.docker.com/subscription/desktop-license/"),
    ]
    rows = [(name, url) for name, url in refs]
    return [
        h1("参考资料"),
        p(f"以下资料均在 {DATE_TEXT.replace('资料核对日期：', '')} 核对。Docker 安装方式会随官方发布变化，正式部署前建议再次打开对应页面确认。"),
        key_value_table(rows),
    ]


def student_manual() -> list:
    story: list = [
        rich("CodeSetArena 学生端<br/>安装与使用手册", "title"),
        p(f"版本：{VERSION}。镜像：codesetarena-student:{VERSION}。默认端口：8000。", "subtitle"),
        p(DATE_TEXT, "subtitle"),
        ui_mock(
            "学生端",
            ["设置", "Stage 1 原始题目", "Stage 2 匿名审稿", "Stage 3 修订打包"],
            [
                ("全局学生信息", "每个功能页顶部填写学号、姓名、班级，保存后所有页面同步。"),
                ("模型配置", "设置页只保留 Base URL、API Key 和模型列表。第一行模型是默认模型。"),
                ("三阶段流程", "先提交原始题目，再完成匿名审稿，最后根据反馈修订并导出。"),
            ],
        ),
        Spacer(1, 0.35 * cm),
        info_box(
            "你需要准备什么",
            "课程发放的学生端本地交付包、Docker、可用浏览器、课程模型 API Key、自己的学号/姓名/班级信息。提交和导出都通过网页按钮完成。",
            BLUE,
        ),
        PageBreak(),
        *platform_install_section(),
        PageBreak(),
        h1("二、启动学生端"),
        p("推荐使用课程离线交付包启动，避免学生电脑直接访问 Docker Hub。如果使用完整 Docker 离线包，学生端交付包位于 docker-offline-v7.1.4/codesetarena/ 目录。Windows WSL 2 和普通 x86_64 Linux 使用 linux-amd64；如果 Docker Server 输出 linux/arm64，请改用 linux-arm64 版本。以下命令在包含学生端交付包的目录执行。"),
        code_block(
            f"""
docker version --format '{{{{.Server.Os}}}}/{{{{.Server.Arch}}}}'
tar -xzf codesetarena-student-local-{VERSION}-{DEFAULT_PACKAGE_PLATFORM}.tar.gz
cd codesetarena-student-local-{VERSION}-{DEFAULT_PACKAGE_PLATFORM}
cp .env.example .env

# 如交付包内含 image.tar，先载入镜像
docker load -i codesetarena-student-{VERSION}.image.tar

# 启动学生端
docker compose up -d

# 打开浏览器
open http://127.0.0.1:8000
            """
        ),
        p("Windows PowerShell 中没有 open 命令时，直接把 http://127.0.0.1:8000 粘贴到浏览器地址栏。"),
        h2("不用 compose 的启动方式"),
        code_block(
            f"""
mkdir -p .codesetarena-student
docker run -d --name codesetarena-student-v714 \\
  -p 8000:8000 \\
  -v "$PWD/.codesetarena-student:/data" \\
  --env-file .env \\
  codesetarena-student:{VERSION}
            """
        ),
        key_value_table(
            [
                ("停止", "docker compose down，或 docker stop codesetarena-student-v714。"),
                ("数据目录", "compose 默认把数据保存到 student/data；docker run 示例保存到 .codesetarena-student。"),
                ("重新启动", "docker compose up -d；已有数据会继续保留。"),
            ]
        ),
        PageBreak(),
        h1("三、设置页"),
        flow_diagram(["打开设置", "填写模型配置", "保存", "返回 Stage"], GREEN),
        step_table(
            [
                (
                    "Base URL",
                    "默认 https://api.deepseek.com。若课程使用其它兼容 OpenAI API 的服务，按助教通知填写。",
                    "保存后页面显示新的 Base URL。",
                ),
                (
                    "API Key",
                    "默认可从 .env 的 API_KEY 读取，页面只显示掩码。需要手动更换时，直接清空并输入新 Key 后保存。",
                    "Key 不会进入提交包。",
                ),
                (
                    "模型列表",
                    "每行一个模型。第一行是默认模型，例如 deepseek-v4-flash，第二行 deepseek-v4-pro。",
                    "Stage 页面模型下拉框同步更新。",
                ),
            ]
        ),
        info_box(
            "学生信息在哪里填",
            "学号、姓名、班级不在设置页，而是在每个功能页顶部。任意页面保存后，其它页面会同步更新；导入包时也会自动读取包内学生信息。",
            GREEN,
        ),
        PageBreak(),
        h1("四、Stage 1 原始题目"),
        ui_mock(
            "学生端 Stage 1",
            ["学生信息", "题目列表", "题目详情", "导出"],
            [
                ("题目列表", "展示题目、已选有效运行数和打包状态。选择 5 道有效题目后导出。"),
                ("题目详情", "编辑题面、函数签名、参考答案、2 条样例数据、5 条测试数据和说明。"),
                ("校验与模型自测", "先保存并校验参考答案，再运行模型。可选择 1-5 条有效运行记录用于打包。"),
            ],
        ),
        step_table(
            [
                (
                    "1",
                    "在顶部保存学生信息。学号会用于导出包命名。",
                    "保存按钮变灰，表示无未保存变更。",
                ),
                (
                    "2",
                    "新建题目或打开已有题目。题面和参考答案输入框较高，适合直接编辑。",
                    "题目详情页打开。",
                ),
                (
                    "3",
                    "填写函数签名、参考答案、样例数据和测试数据。每条测试为输入 JSON 对象和期望输出 JSON 值。",
                    "每行格式提示为正确。",
                ),
                (
                    "4",
                    "点击保存题目并校验参考答案。系统会执行参考答案和 7 个测试用例。",
                    "状态显示校验通过。",
                ),
                (
                    "5",
                    "选择模型并点击运行模型自测。运行记录会保留原始请求和原始返回，但页面只展示必要信息。",
                    "模型自测记录出现。",
                ),
                (
                    "6",
                    "勾选 1-5 条与当前题目匹配的有效运行记录，保存运行记录选择。",
                    "已选有效运行数更新。",
                ),
                (
                    "7",
                    "回到题目列表，选择 5 道可打包题目并导出。",
                    "得到 {学号}-student-stage1-problems.tar.gz。",
                ),
            ]
        ),
        info_box(
            "题目质量提醒",
            "每题必须有唯一确定输出。参考答案通常应在 1 秒内完成；系统单用例超时阈值是 10 秒，只用于弥补硬件差异，不鼓励靠超时制造难点。",
            AMBER,
        ),
        PageBreak(),
        h1("五、Stage 2 匿名审稿"),
        flow_diagram(["导入助教包", "阅读匿名题目", "选择结论", "填写建议", "导出审稿包"], BLUE),
        step_table(
            [
                (
                    "1",
                    "导入 {学号}-teacher-stage2-review-assignment.tar.gz。",
                    "页面显示分配到的匿名题目。",
                ),
                (
                    "2",
                    "查看题目完整详情、样例数据、测试数据和提交的模型自测结果。",
                    "可以判断题目是否清晰、是否有错误、测试是否足够。",
                ),
                (
                    "3",
                    "为每题选择结论：accept、minor、major、reject。默认是未选择，必须改成有效结论。",
                    "未选择会阻止导出。",
                ),
                (
                    "4",
                    "填写建议，指出具体问题或改进方向。",
                    "建议内容保存成功。",
                ),
                (
                    "5",
                    "导出 Stage 2 审稿包。",
                    "得到 {学号}-student-stage2-reviews.tar.gz。",
                ),
            ]
        ),
        PageBreak(),
        h1("六、Stage 3 修订打包"),
        flow_diagram(["导入反馈", "编辑修订题目", "重新校验", "模型自测", "评价审稿意见", "导出"], GREEN),
        step_table(
            [
                (
                    "1",
                    "导入 {学号}-teacher-stage3-review-feedback.tar.gz。",
                    "看到每道题收到的审稿意见。",
                ),
                (
                    "2",
                    "在页面中直接修改题面、函数签名、参考答案、样例数据和测试数据。",
                    "修订后的完整题目保存在系统中。",
                ),
                (
                    "3",
                    "保存并校验参考答案。题目变更后旧校验和旧运行记录会失效。",
                    "状态显示校验通过。",
                ),
                (
                    "4",
                    "重新运行模型自测，并选择 1-5 条当前有效运行记录。",
                    "修订后模型自测记录被选中。",
                ),
                (
                    "5",
                    "对每条审稿意见选择评分：完全采纳、部分采纳、有一定价值、帮助有限、基本无帮助，并填写回应建议。",
                    "所有评分和回应都完整。",
                ),
                (
                    "6",
                    "导出修订提交包。",
                    "得到 {学号}-student-stage3-revision.tar.gz。",
                ),
            ]
        ),
        *common_troubleshooting(8000),
        PageBreak(),
        *sources_section(),
    ]
    return story


def teacher_manual() -> list:
    story: list = [
        rich("CodeSetArena 助教端<br/>安装与使用手册", "title"),
        p(f"版本：{VERSION}。镜像：codesetarena-teacher:{VERSION}。默认端口：8010。", "subtitle"),
        p(DATE_TEXT, "subtitle"),
        ui_mock(
            "助教端",
            [
                "设置",
                "Stage 1 收包验证",
                "Stage 2 审稿分配",
                "Stage 2 收审稿包",
                "Stage 3 发修订反馈",
                "正式评测",
            ],
            [
                ("独立工作目录", "助教端数据默认保存在 .codesetarena-teacher 或 compose 的 data 目录。"),
                ("课程流程", "先收学生原始题包，再分配审稿，收审稿包，发修订反馈，最后收修订包。"),
                ("论文相关", "benchmark 管理、paper export 和论文图表暂不在助教端，本轮保留为 TODO。"),
            ],
        ),
        Spacer(1, 0.35 * cm),
        info_box(
            "你需要准备什么",
            "课程发放的助教端本地交付包、Docker、浏览器、课程模型 API Key、学生名单和学生提交包目录。所有上传和导出都通过网页选择文件或下载完成。",
            BLUE,
        ),
        PageBreak(),
        *platform_install_section(),
        PageBreak(),
        h1("二、启动助教端"),
        p("推荐使用课程离线交付包启动。若使用完整 Docker 离线包，助教端交付包位于 docker-offline-v7.1.4/codesetarena/ 目录。Windows WSL 2 和普通 x86_64 Linux 使用 linux-amd64；如果 Docker Server 输出 linux/arm64，请改用 linux-arm64 版本。助教端默认使用 8010 端口，避免和学生端 8000 冲突。"),
        code_block(
            f"""
docker version --format '{{.Server.Os}}/{{.Server.Arch}}'
tar -xzf codesetarena-teacher-local-{VERSION}-{DEFAULT_PACKAGE_PLATFORM}.tar.gz
cd codesetarena-teacher-local-{VERSION}-{DEFAULT_PACKAGE_PLATFORM}
cp .env.example .env

# 如交付包内含 image.tar，先载入镜像
docker load -i codesetarena-teacher-{VERSION}.image.tar

# 启动助教端
docker compose up -d

# 打开浏览器
open http://127.0.0.1:8010
            """
        ),
        h2("不用 compose 的启动方式"),
        code_block(
            f"""
mkdir -p .codesetarena-teacher
docker run -d --name codesetarena-teacher-v714 \\
  -p 8010:8010 \\
  -v "$PWD/.codesetarena-teacher:/data" \\
  --env-file .env \\
  codesetarena-teacher:{VERSION}
            """
        ),
        key_value_table(
            [
                ("停止", "docker compose down，或 docker stop codesetarena-teacher-v714。"),
                ("数据目录", "compose 默认把数据保存到 teacher/data；docker run 示例保存到 .codesetarena-teacher。"),
                ("与学生端并行", "学生端用 8000，助教端用 8010，可同时运行。"),
            ]
        ),
        PageBreak(),
        h1("三、设置页"),
        step_table(
            [
                (
                    "Base URL",
                    "默认 https://api.deepseek.com。若正式评测使用其它兼容 OpenAI API 的服务，按课程配置填写。",
                    "保存后正式评测使用该地址。",
                ),
                (
                    "API Key",
                    "默认可从 .env 的 API_KEY 读取，页面只显示掩码。清空输入框并保存即可清除本地覆盖值。",
                    "密钥不会进入学生提交包或统计导出。",
                ),
                (
                    "模型列表",
                    "每行一个模型。第一行是默认模型；正式评测可按课程要求扩展多模型列表。",
                    "评测页面下拉或任务配置同步更新。",
                ),
            ]
        ),
        PageBreak(),
        h1("四、Stage 1 收包验证"),
        flow_diagram(["上传学生包", "校验 manifest/hash", "校验题目和运行记录", "查看结果"], BLUE),
        step_table(
            [
                (
                    "1",
                    "上传学生提交的 {学号}-student-stage1-problems.tar.gz。",
                    "文件名识别出学号。",
                ),
                (
                    "2",
                    "系统检查 tar 路径穿越、manifest、hash、学生信息、题目数量、reference/tests 和运行记录。",
                    "合格包显示验证通过。",
                ),
                (
                    "3",
                    "错误包会保留失败原因，例如题数不足、hash mismatch、文件名不合法或运行记录不完整。",
                    "助教可反馈学生重交。",
                ),
            ]
        ),
        h1("五、Stage 2 审稿分配"),
        info_box(
            "审稿数 x 的含义",
            "页面填写的是每道题需要的总审稿份数 x。系统固定把 1 份分配给 AI，剩余 x-1 份由人类学生完成。AI 的学号、姓名、班级均为 AI，AI 包名是 AI-teacher-stage2-review-assignment.tar.gz，包含全部学生的全部题目。",
            GREEN,
        ),
        step_table(
            [
                (
                    "1",
                    "确认 Stage 1 通过验证的学生包列表。",
                    "学生数和题目数正确。",
                ),
                (
                    "2",
                    "输入每道题总审稿份数 x，例如 2 表示 1 份 AI + 1 份人类。",
                    "分配预览无自审冲突。",
                ),
                (
                    "3",
                    "生成审稿包。",
                    "得到 teacher-stage2-review-assignments.tar.gz，以及每名学生的 {学号}-teacher-stage2-review-assignment.tar.gz。",
                ),
            ]
        ),
        PageBreak(),
        h1("六、Stage 2 收审稿包"),
        step_table(
            [
                (
                    "1",
                    "上传 {学号}-student-stage2-reviews.tar.gz。",
                    "系统识别审稿人。",
                ),
                (
                    "2",
                    "系统校验只能审分配题、结论不能是未选择、建议字段完整。",
                    "完成率更新。",
                ),
                (
                    "3",
                    "收齐后进入 Stage 3 发修订反馈。",
                    "每题审稿意见可汇总。",
                ),
            ]
        ),
        h1("七、Stage 3 发修订反馈"),
        flow_diagram(["汇总审稿意见", "生成反馈包", "发给学生"], GREEN),
        step_table(
            [
                (
                    "1",
                    "选择已收齐审稿意见的学生和题目。",
                    "反馈清单完整。",
                ),
                (
                    "2",
                    "生成 {学号}-teacher-stage3-review-feedback.tar.gz。",
                    "可下载单个学生反馈包。",
                ),
                (
                    "3",
                    "也可生成 teacher-stage3-review-feedbacks.tar.gz 批量包。",
                    "便于统一发放。",
                ),
            ]
        ),
        h1("八、Stage 3 收修订包"),
        step_table(
            [
                (
                    "1",
                    "上传 {学号}-student-stage3-revision.tar.gz。",
                    "学生信息和修订题目被读取。",
                ),
                (
                    "2",
                    "系统校验修订题、作者回应、审稿意见评分、新自测运行记录和原始/修订 hash。",
                    "修订完成状态更新。",
                ),
                (
                    "3",
                    "错误包显示具体失败原因。",
                    "可要求学生修正后重交。",
                ),
            ]
        ),
        PageBreak(),
        h1("九、正式评测、统计和审计"),
        step_table(
            [
                (
                    "正式评测",
                    "对收齐的题目执行助教正式多模型运行，run_origin 标记为 ta_official_eval，与学生自测区分。",
                    "生成 teacher-stage4-official-eval.tar.gz。",
                ),
                (
                    "课程统计",
                    "导出包验证、审稿完成、修订完成、模型通过率、相似簇等课程统计。",
                    "生成 teacher-stage4-course-stats.json。",
                ),
                (
                    "审计记录",
                    "查看上传、生成、评测和导出动作。",
                    "问题可追溯。",
                ),
            ]
        ),
        info_box(
            "暂不包含论文端",
            "论文数据筛选、benchmark 管理、paper export 和论文图表将来单独做论文端前端，不放在当前助教端里。",
            AMBER,
        ),
        *common_troubleshooting(8010),
        PageBreak(),
        *sources_section(),
    ]
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
    V7_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, V7_DIR / filename)
    return path


def main() -> None:
    register_fonts()
    student_path = build_pdf(f"CodeSetArena-学生端-安装使用手册-{VERSION}.pdf", student_manual())
    teacher_path = build_pdf(f"CodeSetArena-助教端-安装使用手册-{VERSION}.pdf", teacher_manual())
    print(student_path)
    print(teacher_path)
    print(V7_DIR / student_path.name)
    print(V7_DIR / teacher_path.name)


if __name__ == "__main__":
    main()
