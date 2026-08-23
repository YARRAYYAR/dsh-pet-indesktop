from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pdf" / "dsh-pet-indesktop-project-report.pdf"
FONT = Path("/Users/ray/Library/Fonts/SimHei.ttf")
ICON = ROOT / "assets" / "app-icon.png"


def register_fonts() -> str:
    if FONT.exists():
        pdfmetrics.registerFont(TTFont("ProjectSans", str(FONT)))
        return "ProjectSans"
    pdfmetrics.registerFont(TTFont("ProjectSans", "/System/Library/Fonts/STHeiti Light.ttc"))
    return "ProjectSans"


def p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D7E5F2"))
    canvas.line(18 * mm, 15 * mm, 192 * mm, 15 * mm)
    canvas.setFillColor(colors.HexColor("#6C8298"))
    canvas.setFont("ProjectSans", 8)
    canvas.drawString(18 * mm, 10 * mm, "DSH-Pet project report")
    canvas.drawRightString(192 * mm, 10 * mm, f"{doc.page}")
    canvas.restoreState()


def build() -> Path:
    font_name = register_fonts()
    OUT.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=17 * mm,
        bottomMargin=22 * mm,
        title="DSH-Pet 项目交付报告",
        author="Codex",
    )

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "TitleZH", parent=styles["Title"], fontName=font_name, fontSize=25,
        leading=33, textColor=colors.HexColor("#12385A"), alignment=TA_CENTER,
        spaceAfter=6 * mm,
    )
    subtitle = ParagraphStyle(
        "SubtitleZH", parent=styles["Normal"], fontName=font_name, fontSize=11,
        leading=18, textColor=colors.HexColor("#54728E"), alignment=TA_CENTER,
        spaceAfter=8 * mm,
    )
    h1 = ParagraphStyle(
        "Heading1ZH", parent=styles["Heading1"], fontName=font_name, fontSize=16,
        leading=23, textColor=colors.HexColor("#12385A"), spaceBefore=5 * mm,
        spaceAfter=3 * mm,
    )
    h2 = ParagraphStyle(
        "Heading2ZH", parent=styles["Heading2"], fontName=font_name, fontSize=11.5,
        leading=17, textColor=colors.HexColor("#1B6085"), spaceBefore=3 * mm,
        spaceAfter=1.5 * mm,
    )
    body = ParagraphStyle(
        "BodyZH", parent=styles["BodyText"], fontName=font_name, fontSize=9.4,
        leading=16, textColor=colors.HexColor("#243746"), alignment=TA_LEFT,
        spaceAfter=2.2 * mm,
    )
    small = ParagraphStyle(
        "SmallZH", parent=body, fontSize=8.3, leading=13, textColor=colors.HexColor("#53697B"),
    )
    cell = ParagraphStyle(
        "CellZH", parent=body, fontSize=8.4, leading=13, spaceAfter=0,
    )
    cell_bold = ParagraphStyle(
        "CellBoldZH", parent=cell, textColor=colors.HexColor("#12385A"),
    )
    cell_header = ParagraphStyle(
        "CellHeaderZH", parent=cell, textColor=colors.white,
    )
    bullet = ParagraphStyle(
        "BulletZH", parent=body, leftIndent=5 * mm, firstLineIndent=-3 * mm,
        bulletIndent=0, spaceAfter=1.1 * mm,
    )

    story = []
    if ICON.exists():
        icon = Image(str(ICON), width=32 * mm, height=32 * mm)
        icon.hAlign = "CENTER"
        story.extend([Spacer(1, 5 * mm), icon, Spacer(1, 4 * mm)])
    story.extend([
        p("DSH-Pet", title),
        p("桌面动态宠物项目交付报告", subtitle),
        p("版本范围：当前工作区代码与素材 · 生成日期：" + date.today().isoformat(), subtitle),
    ])

    summary_data = [
        [p("项目", cell_bold), p("DSH-Pet 独立桌面宠物", cell)],
        [p("代码仓库", cell_bold), p("https://github.com/MerZlin/dsh-pet-indesktop", cell)],
        [p("上传分支", cell_bold), p("codex/upload-interaction-pdf", cell)],
        [p("运行形态", cell_bold), p("macOS 独立应用，状态栏菜单控制，桌面透明窗口展示", cell)],
        [p("角色素材", cell_bold), p("shenshen，91 段 WebM 动画，包含互动、移动、待机、随机和转身分类", cell)],
    ]
    summary = Table(summary_data, colWidths=[30 * mm, 144 * mm], hAlign="CENTER")
    summary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF4FB")),
        ("BACKGROUND", (1, 0), (1, -1), colors.HexColor("#F8FBFE")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#B9D4E8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D7E5F2")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2 * mm),
    ]))
    story.extend([summary, PageBreak()])

    story.append(p("1. 本次交付内容", h1))
    for item in [
        "桌面宠物基础运行：透明窗口、状态栏菜单、动画播放和退出控制。",
        "互动反馈：双击、长按、拖拽、快速连续点击、鼠标靠近注视、边缘反弹和主动问候。",
        "动作收藏夹与播放列表：91 段动画可收藏，可按收藏列表循环、顺序或随机播放。",
        "全局快捷键：显示或隐藏、暂停或继续、随机动作、鼠标穿透、尖叫鸭。",
        "情绪与性格：安静、活泼、调皮三种模式，分别调整待机、转身、主动动作和问候概率。",
        "媒体质量处理：保留高画质 WebM 资产，并在透明区执行 Alpha=1 清理，降低透明噪声和边缘残留。",
        "发布准备：保留 macOS 应用构建方式、超分处理脚本、测试脚本和图标资源。",
    ]:
        story.append(p("• " + item, bullet))

    story.append(p("2. 架构说明", h1))
    architecture = [
        [p("层", cell_header), p("主要文件", cell_header), p("职责", cell_header)],
        [p("应用入口", cell_bold), p("pet/app.py", cell), p("创建 QApplication、状态栏菜单、全局快捷键和生命周期管理。", cell)],
        [p("桌面窗口", cell_bold), p("pet/window.py", cell), p("处理窗口展示、动画状态、鼠标交互、播放列表、性格模式和菜单动作。", cell)],
        [p("素材目录", cell_bold), p("pet/catalog.py\npet/library.py", cell), p("发现角色、分类动作、收藏集合和动画元数据，减少窗口层对文件结构的耦合。", cell)],
        [p("媒体播放", cell_bold), p("pet/webm_clip.py", cell), p("读取 WebM 帧、处理透明通道、固定画布绘制，避免窗口内容随动画帧抖动。", cell)],
        [p("交互与声音", cell_bold), p("pet/interaction.py\npet/sound.py", cell), p("集中管理点击、拖拽、边缘状态、靠近注视和尖叫鸭反馈。", cell)],
        [p("可扩展控制", cell_bold), p("pet/action_dialog.py\npet/hotkeys.py", cell), p("动作选择对话框与 macOS Carbon 全局快捷键注册，后续可扩展更多控制项。", cell)],
    ]
    arch_table = Table(architecture, colWidths=[25 * mm, 45 * mm, 104 * mm], repeatRows=1)
    arch_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B6085")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F8FBFE")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F8FBFE"), colors.HexColor("#EEF6FB")]),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#B9D4E8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CFE0EC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]))
    story.extend([arch_table, Spacer(1, 3 * mm)])
    story.append(p("设计原则：高频动画播放逻辑与低频控制面板分离；配置写入用户目录；素材代际保持独立，便于后续替换超分版本或新增角色。", body))

    story.append(p("3. 操作说明", h1))
    for item in [
        "右键状态栏图标：打开动作管理、收藏夹、播放列表、性格模式和显示控制。",
        "动作收藏：在动作管理中勾选需要的动画，确认后可将收藏集设为播放列表。",
        "播放模式：关闭、顺序循环、随机循环三种状态；播放列表为空时自动回退到普通动作逻辑。",
        "性格模式：安静减少主动动作，活泼保持平衡，调皮提高随机动作和主动问候频率。",
        "默认全局快捷键：Control + Option + Command + H 显示或隐藏；P 暂停；R 随机动作；M 鼠标穿透；D 尖叫鸭。",
        "鼠标穿透开启后，窗口不接收鼠标命中；再次使用快捷键 M 或状态栏菜单即可恢复。",
    ]:
        story.append(p("• " + item, bullet))

    story.append(p("4. 质量验证", h1))
    validation = [
        [p("检查项", cell_header), p("结果", cell_header), p("证据", cell_header)],
        [p("运行时单元测试", cell), p("通过", cell_bold), p("tests.test_runtime 与 tests.test_media_runtime：6 tests OK。", cell)],
        [p("交互辅助测试", cell), p("通过", cell_bold), p("offscreen 交互、收藏夹、性格和播放列表 harness 均返回 OK。", cell)],
        [p("全局快捷键", cell), p("通过", cell_bold), p("注册测试返回 HOTKEY_START True True None，停止后 HOTKEY_STOP False。", cell)],
        [p("动画素材", cell), p("通过", cell_bold), p("应用日志记录 shenshen 91 段动画加载完成。", cell)],
        [p("macOS 应用", cell), p("通过", cell_bold), p("/Applications/DSH-Pet.app 已验证签名并可启动。", cell)],
        [p("交付压缩包", cell), p("通过", cell_bold), p("DSH-Pet-macos-arm64-collections-hotkeys.zip 已通过 unzip -tq。", cell)],
    ]
    validation_table = Table(validation, colWidths=[35 * mm, 18 * mm, 121 * mm], repeatRows=1)
    validation_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B6085")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F8FBFE"), colors.HexColor("#EEF6FB")]),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#B9D4E8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CFE0EC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]))
    story.append(validation_table)

    story.append(p("5. 文件交付位置", h1))
    paths = [
        ("源代码", str(ROOT)),
        ("macOS 应用", "/Applications/DSH-Pet.app"),
        ("应用压缩包", "/Users/ray/Downloads/DSH-Pet-macos-arm64-collections-hotkeys.zip"),
        ("本 PDF", str(OUT)),
        ("GitHub 分支", "https://github.com/MerZlin/dsh-pet-indesktop/tree/codex/upload-interaction-pdf"),
    ]
    path_rows = [[p("交付物", cell_header), p("路径或地址", cell_header)]]
    path_rows.extend([[p(name, cell), p(value, small)] for name, value in paths])
    path_table = Table(path_rows, colWidths=[34 * mm, 140 * mm], repeatRows=1)
    path_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B6085")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F8FBFE"), colors.HexColor("#EEF6FB")]),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#B9D4E8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CFE0EC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]))
    story.extend([path_table, Spacer(1, 5 * mm)])
    story.append(p("备注：本报告对应当前工作区交付范围。原始视频、高画质视频、超分工具、应用包和历史备份保持在各自目录中，未在本次上传中覆盖或删除。", body))
    story.append(p("后续升级建议：继续将角色动作元数据、快捷键映射和行为概率配置化；新增角色时复用同一素材目录协议和播放管线。", body))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return OUT


if __name__ == "__main__":
    path = build()
    print(path)
