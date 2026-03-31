"""Generate PDF from SPEC_INVOICING.md"""
import re
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether, HRFlowable
)


def parse_markdown(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    return content


def escape_xml(text):
    """Escape XML special chars for ReportLab paragraphs."""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


def format_inline(text):
    """Convert markdown inline formatting to ReportLab XML."""
    # Bold + italic
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<b><i>\1</i></b>', text)
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # Italic
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    # Inline code
    text = re.sub(r'`([^`]+)`', r'<font face="Courier" size="9">\1</font>', text)
    # Links - just show text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    return text


def build_pdf(md_content, output_path):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        topMargin=2*cm,
        bottomMargin=2*cm,
        leftMargin=2*cm,
        rightMargin=2*cm,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    styles.add(ParagraphStyle(
        'DocTitle', parent=styles['Title'],
        fontSize=22, spaceAfter=6, textColor=HexColor('#1a1a2e'),
        fontName='Helvetica-Bold',
    ))
    styles.add(ParagraphStyle(
        'DocSubtitle', parent=styles['Normal'],
        fontSize=11, spaceAfter=4, textColor=HexColor('#555555'),
        fontName='Helvetica',
    ))
    styles.add(ParagraphStyle(
        'H1', parent=styles['Heading1'],
        fontSize=18, spaceBefore=24, spaceAfter=10,
        textColor=HexColor('#1a1a2e'), fontName='Helvetica-Bold',
    ))
    styles.add(ParagraphStyle(
        'H2', parent=styles['Heading2'],
        fontSize=14, spaceBefore=18, spaceAfter=8,
        textColor=HexColor('#2d3436'), fontName='Helvetica-Bold',
    ))
    styles.add(ParagraphStyle(
        'H3', parent=styles['Heading3'],
        fontSize=12, spaceBefore=14, spaceAfter=6,
        textColor=HexColor('#2d3436'), fontName='Helvetica-Bold',
    ))
    styles.add(ParagraphStyle(
        'BodyText2', parent=styles['Normal'],
        fontSize=10, spaceAfter=6, leading=14,
        fontName='Helvetica',
    ))
    styles.add(ParagraphStyle(
        'CodeBlock', parent=styles['Normal'],
        fontSize=8, fontName='Courier', leading=10,
        spaceBefore=6, spaceAfter=6,
        leftIndent=12, backColor=HexColor('#f5f5f5'),
    ))
    styles.add(ParagraphStyle(
        'BulletItem', parent=styles['Normal'],
        fontSize=10, spaceAfter=3, leading=13,
        leftIndent=20, bulletIndent=8,
        fontName='Helvetica',
    ))
    styles.add(ParagraphStyle(
        'TableCell', parent=styles['Normal'],
        fontSize=8.5, leading=11, fontName='Helvetica',
    ))
    styles.add(ParagraphStyle(
        'TableHeader', parent=styles['Normal'],
        fontSize=8.5, leading=11, fontName='Helvetica-Bold',
        textColor=HexColor('#ffffff'),
    ))

    story = []
    lines = md_content.split('\n')
    i = 0
    in_code_block = False
    code_lines = []
    in_table = False
    table_rows = []

    while i < len(lines):
        line = lines[i]

        # Code block toggle
        if line.strip().startswith('```'):
            if in_code_block:
                # End code block
                code_text = '<br/>'.join(escape_xml(l) for l in code_lines)
                story.append(Paragraph(code_text, styles['CodeBlock']))
                code_lines = []
                in_code_block = False
            else:
                # Flush table if active
                if in_table:
                    _flush_table(story, table_rows, styles)
                    table_rows = []
                    in_table = False
                in_code_block = True
            i += 1
            continue

        if in_code_block:
            code_lines.append(line)
            i += 1
            continue

        # Table detection
        if '|' in line and line.strip().startswith('|'):
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            # Skip separator rows
            if all(re.match(r'^[-:]+$', c) for c in cells):
                i += 1
                continue
            if not in_table:
                in_table = True
            table_rows.append(cells)
            i += 1
            continue
        else:
            if in_table:
                _flush_table(story, table_rows, styles)
                table_rows = []
                in_table = False

        stripped = line.strip()

        # Empty line
        if not stripped:
            i += 1
            continue

        # Horizontal rule
        if stripped == '---':
            story.append(Spacer(1, 6))
            story.append(HRFlowable(
                width="100%", thickness=1,
                color=HexColor('#dddddd'), spaceAfter=6
            ))
            i += 1
            continue

        # Title line (# at start of doc)
        if stripped.startswith('# ') and not stripped.startswith('## '):
            text = stripped[2:].strip()
            # First H1 is the document title
            if len(story) == 0:
                story.append(Paragraph(escape_xml(text), styles['DocTitle']))
            else:
                story.append(Paragraph(format_inline(escape_xml(text)), styles['H1']))
            i += 1
            continue

        # Subtitle line
        if stripped.startswith('# ') and len(story) == 1:
            text = stripped[2:].strip()
            story.append(Paragraph(escape_xml(text), styles['DocSubtitle']))
            i += 1
            continue

        # H2
        if stripped.startswith('## '):
            text = stripped[3:].strip()
            story.append(Paragraph(format_inline(escape_xml(text)), styles['H1']))
            i += 1
            continue

        # H3
        if stripped.startswith('### '):
            text = stripped[4:].strip()
            story.append(Paragraph(format_inline(escape_xml(text)), styles['H2']))
            i += 1
            continue

        # H4
        if stripped.startswith('#### '):
            text = stripped[5:].strip()
            story.append(Paragraph(format_inline(escape_xml(text)), styles['H3']))
            i += 1
            continue

        # Bullet points
        if stripped.startswith('- ') or stripped.startswith('* '):
            text = stripped[2:].strip()
            text = format_inline(escape_xml(text))
            story.append(Paragraph(
                text, styles['BulletItem'],
                bulletText='\u2022'
            ))
            i += 1
            continue

        # Numbered items
        m = re.match(r'^(\d+)\.\s+(.+)$', stripped)
        if m:
            num = m.group(1)
            text = format_inline(escape_xml(m.group(2)))
            story.append(Paragraph(
                text, styles['BulletItem'],
                bulletText=f'{num}.'
            ))
            i += 1
            continue

        # Bold metadata lines (like **Application:** etc)
        if stripped.startswith('**') and ':' in stripped:
            text = format_inline(escape_xml(stripped))
            story.append(Paragraph(text, styles['DocSubtitle']))
            i += 1
            continue

        # Regular paragraph
        text = format_inline(escape_xml(stripped))
        story.append(Paragraph(text, styles['BodyText2']))
        i += 1

    # Flush remaining table
    if in_table:
        _flush_table(story, table_rows, styles)

    doc.build(story)
    return output_path


def _flush_table(story, table_rows, styles):
    if not table_rows:
        return

    # Build table data with Paragraph objects for wrapping
    data = []
    for row_idx, row in enumerate(table_rows):
        if row_idx == 0:
            data.append([Paragraph(format_inline(escape_xml(c)), styles['TableHeader']) for c in row])
        else:
            data.append([Paragraph(format_inline(escape_xml(c)), styles['TableCell']) for c in row])

    ncols = max(len(r) for r in data)
    # Pad rows with fewer columns
    for r in data:
        while len(r) < ncols:
            r.append(Paragraph('', styles['TableCell']))

    # Calculate column widths
    available = 17 * cm
    col_width = available / ncols

    t = Table(data, colWidths=[col_width] * ncols, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#2d3436')),
        ('TEXTCOLOR', (0, 0), (-1, 0), HexColor('#ffffff')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#dddddd')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#ffffff'), HexColor('#f8f9fa')]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(Spacer(1, 4))
    story.append(t)
    story.append(Spacer(1, 6))


if __name__ == '__main__':
    md_path = r'C:\Source\CWA_SCHOOL_APP_2\.claude\worktrees\romantic-perlman\SPEC_INVOICING.md'
    output = r'C:\Source\CWA_SCHOOL_APP_2\.claude\worktrees\romantic-perlman\SPEC_INVOICING.pdf'

    build_pdf(parse_markdown(md_path), output)
    print(f'PDF generated: {output}')
