"""Build the four-page final report from the editable Markdown source."""
from __future__ import annotations

import argparse
import re
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]


def formatted(text):
    text = escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"`(.+?)`", r'<font name="Courier">\1</font>', text)
    return text


def build(source, target):
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=10.3, leading=14.3,
                          textColor=colors.HexColor("#253041"), spaceAfter=8,
                          allowWidows=0, allowOrphans=0)
    title = ParagraphStyle("title", parent=body, fontName="Helvetica-Bold", fontSize=17,
                           leading=20, textColor=colors.HexColor("#17263d"), spaceAfter=7)
    section = ParagraphStyle("section", parent=body, fontName="Helvetica-Bold", fontSize=11.1,
                             leading=14, textColor=colors.HexColor("#24447a"), spaceBefore=5,
                             spaceAfter=5, keepWithNext=True)
    caption = ParagraphStyle("caption", parent=body, fontSize=8, leading=10.2,
                             textColor=colors.HexColor("#566579"), spaceAfter=7)
    table_text = ParagraphStyle("table", parent=body, fontSize=8.7, leading=10.5, spaceAfter=0)
    diagram = ParagraphStyle("diagram", parent=body, fontName="Courier", fontSize=8.6, leading=11.5,
                             backColor=colors.HexColor("#f0f4f8"), borderPadding=7)
    flow = []
    lines = source.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line == "<!-- PAGE BREAK -->":
            flow.append(PageBreak())
            i += 1
            continue
        if line.startswith("```"):
            i += 1
            block = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            if i == len(lines):
                raise ValueError("Unterminated diagram block")
            flow.append(Preformatted("\n".join(block), diagram))
            flow.append(Spacer(1, 7))
            i += 1
            continue
        if line.startswith("# "):
            flow.append(Paragraph(formatted(line[2:]), title))
            i += 1
            continue
        if line.startswith("## "):
            flow.append(Paragraph(formatted(line[3:]), section))
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [x.strip() for x in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r"[-: ]+", cell) for cell in cells):
                    rows.append([Paragraph(formatted(cell), table_text) for cell in cells])
                i += 1
            table = Table(rows, colWidths=[24 * mm, 39 * mm, 33 * mm, 38 * mm, 40 * mm], repeatRows=1)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf0f7")),
                ("LINEBELOW", (0, 0), (-1, 0), .7, colors.HexColor("#b4c1d0")),
                ("LINEBELOW", (0, -1), (-1, -1), .5, colors.HexColor("#cfd8e3")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            flow.extend([table, Spacer(1, 4)])
            continue
        para = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", "|", "<!--", "```")):
            para.append(lines[i].strip())
            i += 1
        text = " ".join(para)
        flow.append(Paragraph(formatted(text), caption if text.startswith("Table 1.") else body))

    target.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(target), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=15 * mm, bottomMargin=16 * mm, title="TokenFlow final report",
                            author="CHEONG KIN NGAI")

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#d4dce6"))
        canvas.line(18 * mm, 12 * mm, A4[0] - 18 * mm, 12 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#66758a"))
        canvas.drawString(18 * mm, 7.5 * mm, "TokenFlow  |  CISC3010")
        canvas.drawRightString(A4[0] - 18 * mm, 7.5 * mm, str(document.page))
        canvas.restoreState()

    doc.build(flow, onFirstPage=footer, onLaterPages=footer)
    print(f"Wrote {target}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "report/TokenFlow_Final_Report.md")
    parser.add_argument("--output", type=Path, default=ROOT / "report/TokenFlow_Final_Report.pdf")
    args = parser.parse_args()
    build(args.source, args.output)
