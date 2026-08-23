from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pdf" / "dsh-pet-indesktop-source-code.pdf"
FONT = Path("/Users/ray/Library/Fonts/SimHei.ttf")


def source_files() -> list[Path]:
    roots = [ROOT / "pet", ROOT / "tests", ROOT / "scripts", ROOT / "tools"]
    suffixes = {".py", ".command", ".md", ".toml", ".yml", ".yaml", ".json"}
    files = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            if any(part.startswith("_tmp") for part in path.parts):
                continue
            if "__pycache__" in path.parts or ".venv" in path.parts:
                continue
            files.append(path)
    for name in (".gitignore", "README.md", "run-mac.command"):
        path = ROOT / name
        if path.exists():
            files.append(path)
    return sorted(set(files), key=lambda path: str(path.relative_to(ROOT)))


def register_font() -> str:
    pdfmetrics.registerFont(TTFont("CodeZH", str(FONT)))
    return "CodeZH"


def footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D7E5F2"))
    canvas.line(12 * mm, 10 * mm, 285 * mm, 10 * mm)
    canvas.setFillColor(colors.HexColor("#6C8298"))
    canvas.setFont("CodeZH", 7)
    canvas.drawString(12 * mm, 6 * mm, "DSH-Pet source code listing")
    canvas.drawRightString(285 * mm, 6 * mm, f"{doc.page}")
    canvas.restoreState()


def build() -> Path:
    font_name = register_font()
    files = source_files()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=landscape(A4),
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=14 * mm,
        title="DSH-Pet 源代码全文",
        author="Codex",
    )

    styles = getSampleStyleSheet()
    cover = ParagraphStyle(
        "Cover", parent=styles["Title"], fontName=font_name, fontSize=24,
        leading=32, alignment=TA_CENTER, textColor=colors.HexColor("#12385A"),
        spaceAfter=6 * mm,
    )
    sub = ParagraphStyle(
        "Sub", parent=styles["Normal"], fontName=font_name, fontSize=11,
        leading=18, alignment=TA_CENTER, textColor=colors.HexColor("#54728E"),
    )
    heading = ParagraphStyle(
        "FileHeading", parent=styles["Heading2"], fontName=font_name, fontSize=11,
        leading=16, textColor=colors.white, backColor=colors.HexColor("#1B6085"),
        leftIndent=2 * mm, borderPadding=2 * mm, spaceBefore=2 * mm, spaceAfter=2 * mm,
    )
    toc_heading = ParagraphStyle(
        "TocHeading", parent=styles["Heading1"], fontName=font_name, fontSize=16,
        leading=23, textColor=colors.HexColor("#12385A"), spaceAfter=3 * mm,
    )
    normal = ParagraphStyle(
        "NormalZH", parent=styles["Normal"], fontName=font_name, fontSize=9,
        leading=15, textColor=colors.HexColor("#243746"),
    )
    code = ParagraphStyle(
        "CodeZH", parent=styles["Code"], fontName=font_name, fontSize=5.3,
        leading=6.5, leftIndent=0, rightIndent=0, spaceBefore=0, spaceAfter=0,
        textColor=colors.HexColor("#1F2933"), backColor=colors.HexColor("#F7FAFC"),
    )
    toc_cell = ParagraphStyle(
        "TocCell", parent=normal, fontSize=8.3, leading=12, spaceAfter=0,
    )
    toc_header = ParagraphStyle(
        "TocHeader", parent=toc_cell, textColor=colors.white,
    )

    story = [
        Spacer(1, 25 * mm),
        Paragraph("DSH-Pet", cover),
        Paragraph("源代码全文 PDF", cover),
        Paragraph("逐文件收录当前工作区代码，带文件名与行号", sub),
        Spacer(1, 8 * mm),
        Paragraph("生成日期：" + date.today().isoformat(), sub),
        Paragraph("范围：pet / tests / scripts / tools 及根目录代码配置", sub),
        Spacer(1, 12 * mm),
        Paragraph("说明：行号和文件标题是 PDF 排版辅助信息；代码正文按文件内容输出。视频、图片、模型和临时运行产物不属于代码，未写入本 PDF。", normal),
        PageBreak(),
        Paragraph("文件目录", toc_heading),
    ]

    toc_rows = [[Paragraph("序号", toc_header), Paragraph("文件", toc_header), Paragraph("行数", toc_header)]]
    for index, path in enumerate(files, 1):
        text = path.read_text(encoding="utf-8", errors="replace")
        toc_rows.append([
            Paragraph(str(index), toc_cell),
            Paragraph(str(path.relative_to(ROOT)), toc_cell),
            Paragraph(str(len(text.splitlines())), toc_cell),
        ])
    toc = Table(toc_rows, colWidths=[18 * mm, 210 * mm, 25 * mm], repeatRows=1)
    toc.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B6085")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F7FAFC"), colors.HexColor("#EAF4FB")]),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#B9D4E8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CFE0EC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2 * mm),
    ]))
    story.extend([toc, PageBreak()])

    for index, path in enumerate(files, 1):
        relative = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        numbered = "\n".join(f"{line_no:5d} | {line}" for line_no, line in enumerate(lines, 1))
        story.append(Paragraph(f"{index:02d}. {relative}  ({len(lines)} lines)", heading))
        story.append(Preformatted(numbered, code, maxLineLength=170))
        story.append(Spacer(1, 4 * mm))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(f"files={len(files)}")
    print(f"output={OUT}")
    return OUT


if __name__ == "__main__":
    build()
