"""Render a period report to PDF (CPP-388).

ReportLab, drawing the same charts the web view shows — a PDF that dropped the
charts and kept the tables would be a downgrade the reader did not ask for, and
the parent who downloads it is often the one who never opens the web page.

Everything is read off ``PeriodReport.data``, the same frozen snapshot the HTML
template renders, so the two can never disagree.
"""

from io import BytesIO

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
    TableStyle,
)

INK = colors.HexColor('#1f2937')
MUTED = colors.HexColor('#6b7280')
ACCENT = colors.HexColor('#4f46e5')
GOOD = colors.HexColor('#059669')
WARN = colors.HexColor('#d97706')
BAD = colors.HexColor('#dc2626')
RULE = colors.HexColor('#e5e7eb')

# Enough distinct slices for the "1 / 2 / 3+" attempt buckets with headroom.
SLICE_COLOURS = [
    colors.HexColor('#c7d2fe'), colors.HexColor('#818cf8'),
    colors.HexColor('#4338ca'), colors.HexColor('#a5b4fc'),
]

CONTENT_WIDTH = A4[0] - 36 * mm


def _styles():
    base = getSampleStyleSheet()
    return {
        'title': ParagraphStyle(
            'ReportTitle', parent=base['Title'], fontSize=20, leading=24,
            textColor=INK, spaceAfter=2,
        ),
        'subtitle': ParagraphStyle(
            'ReportSubtitle', parent=base['Normal'], fontSize=10.5, leading=14,
            textColor=MUTED, spaceAfter=10,
        ),
        'heading': ParagraphStyle(
            'ReportHeading', parent=base['Heading2'], fontSize=13, leading=16,
            textColor=INK, spaceBefore=12, spaceAfter=6,
        ),
        'body': ParagraphStyle(
            'ReportBody', parent=base['Normal'], fontSize=9.5, leading=13,
            textColor=INK,
        ),
        'note': ParagraphStyle(
            'ReportNote', parent=base['Normal'], fontSize=9, leading=12,
            textColor=MUTED,
        ),
        'caption': ParagraphStyle(
            'ReportCaption', parent=base['Normal'], fontSize=8.5, leading=11,
            textColor=MUTED, alignment=TA_CENTER,
        ),
        'cell': ParagraphStyle(
            'ReportCell', parent=base['Normal'], fontSize=8.5, leading=10.5,
            textColor=INK,
        ),
    }


def _score_colour(pct):
    if pct >= 75:
        return GOOD
    if pct >= 50:
        return WARN
    return BAD


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def _topic_chart(topics):
    """Accuracy per topic, weakest first — mirrors the bar chart on the page."""
    rows = topics[:10]
    if not rows:
        return None

    height = 60 + 18 * len(rows)
    drawing = Drawing(CONTENT_WIDTH, height)
    chart = VerticalBarChart()
    chart.x = 30
    chart.y = 40
    chart.width = CONTENT_WIDTH - 50
    chart.height = height - 60
    chart.data = [[row['accuracy_pct'] for row in rows]]
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = 100
    chart.valueAxis.valueStep = 25
    chart.categoryAxis.categoryNames = [_shorten(row['topic']) for row in rows]
    chart.categoryAxis.labels.angle = 25
    chart.categoryAxis.labels.dy = -6
    chart.categoryAxis.labels.boxAnchor = 'ne'
    chart.categoryAxis.labels.fontSize = 7
    chart.barWidth = 6
    chart.groupSpacing = 8
    for index, row in enumerate(rows):
        chart.bars[(0, index)].fillColor = _score_colour(row['accuracy_pct'])
    drawing.add(chart)
    return drawing


def _attempts_pie(distribution):
    """How many homeworks were attempted once / twice / three or more times."""
    slices = [entry for entry in distribution if entry['count']]
    if not slices:
        return None

    drawing = Drawing(CONTENT_WIDTH, 150)
    pie = Pie()
    pie.x = 40
    pie.y = 15
    pie.width = 120
    pie.height = 120
    pie.data = [entry['count'] for entry in slices]
    pie.labels = [f"{entry['label']}×" for entry in slices]
    pie.slices.strokeWidth = 0.5
    pie.slices.strokeColor = colors.white
    pie.sideLabels = True
    for index in range(len(slices)):
        pie.slices[index].fillColor = SLICE_COLOURS[index % len(SLICE_COLOURS)]
    drawing.add(pie)

    legend = Legend()
    legend.x = 210
    legend.y = 110
    legend.fontSize = 8.5
    legend.alignment = 'right'
    legend.dxTextSpace = 6
    legend.deltay = 13
    legend.colorNamePairs = [
        (SLICE_COLOURS[index % len(SLICE_COLOURS)],
         f"{entry['label']} attempt{'' if entry['label'] == '1' else 's'} "
         f"— {entry['count']} homework")
        for index, entry in enumerate(slices)
    ]
    drawing.add(legend)
    return drawing


def _trend_chart(trend):
    """Average score over the period. Needs two points to be a line at all."""
    if len(trend) < 2:
        return None

    drawing = Drawing(CONTENT_WIDTH, 160)
    chart = HorizontalLineChart()
    chart.x = 30
    chart.y = 35
    chart.width = CONTENT_WIDTH - 50
    chart.height = 105
    chart.data = [[point['avg_pct'] for point in trend]]
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = 100
    chart.valueAxis.valueStep = 25
    chart.categoryAxis.categoryNames = [point['label'] for point in trend]
    chart.categoryAxis.labels.angle = 25
    chart.categoryAxis.labels.dy = -6
    chart.categoryAxis.labels.boxAnchor = 'ne'
    chart.categoryAxis.labels.fontSize = 7
    chart.lines[0].strokeColor = ACCENT
    chart.lines[0].strokeWidth = 2
    chart.lines[0].symbol = None
    drawing.add(chart)
    return drawing


def _shorten(text, limit=22):
    return text if len(text) <= limit else text[:limit - 1] + '…'


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

def _kpi_table(totals):
    cells = [
        ('Average (best attempt)', f'{totals.get("avg_best_pct", 0)}%'),
        ('Average (first attempt)', f'{totals.get("avg_first_pct", 0)}%'),
        ('Gained by retrying', f'{totals.get("improvement_pct", 0):+d} pts'),
        ('Homework attempted', str(totals.get('homework_attempted', 0))),
        ('Total attempts', str(totals.get('submissions', 0))),
        ('Time on task', f'{totals.get("time_minutes", 0)} min'),
        ('Completed on time', f'{totals.get("on_time_pct", 0)}%'),
        ('Best single score', f'{totals.get("best_single_pct", 0)}%'),
    ]
    # Four across, two rows: labels above their values so the numbers read as
    # a dashboard rather than a spreadsheet.
    columns = 4
    rows = []
    for offset in range(0, len(cells), columns):
        chunk = cells[offset:offset + columns]
        rows.append([label for label, _ in chunk])
        rows.append([value for _, value in chunk])

    table = Table(rows, colWidths=[CONTENT_WIDTH / columns] * columns)
    style = [
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('BOX', (0, 0), (-1, -1), 0.5, RULE),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, RULE),
    ]
    for index in range(len(rows)):
        if index % 2 == 0:
            style += [
                ('FONTSIZE', (0, index), (-1, index), 7.5),
                ('TEXTCOLOR', (0, index), (-1, index), MUTED),
                ('BOTTOMPADDING', (0, index), (-1, index), 0),
                ('LINEBELOW', (0, index), (-1, index), 0, colors.white),
            ]
        else:
            style += [
                ('FONTSIZE', (0, index), (-1, index), 14),
                ('FONTNAME', (0, index), (-1, index), 'Helvetica-Bold'),
                ('TEXTCOLOR', (0, index), (-1, index), ACCENT),
                ('TOPPADDING', (0, index), (-1, index), 0),
            ]
    table.setStyle(TableStyle(style))
    return table


def _data_table(header, rows, widths, aligns=None, wrap_first=True):
    """A header + body table whose first column wraps.

    ReportLab does not wrap a bare string in a cell — it overflows into the
    neighbouring column — and homework titles and topic names are exactly the
    values long enough to do it. Wrapping the label column in a Paragraph is
    what keeps a real title readable instead of printed over the score.
    """
    if wrap_first:
        cell = _styles()['cell']
        rows = [[Paragraph(str(row[0]), cell)] + list(row[1:]) for row in rows]

    table = Table([header] + rows, colWidths=widths, repeatRows=1)
    style = [
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BACKGROUND', (0, 0), (-1, 0), INK),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9fafb')]),
        ('GRID', (0, 0), (-1, -1), 0.4, RULE),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]
    for column, align in enumerate(aligns or []):
        style.append(('ALIGN', (column, 0), (column, -1), align))
    table.setStyle(TableStyle(style))
    return table


def _awards_block(awards, styles):
    flow = []
    for award in awards:
        flow.append(Paragraph(
            f'<b>{award["label"]}</b> — {award["detail"]}', styles['body'],
        ))
        flow.append(Spacer(1, 3))
    return flow


def _empty_note(styles):
    return Paragraph(
        'No homework was submitted in this period, so there is nothing to '
        'report yet. Every attempt counts — including the second one.',
        styles['note'],
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def render_report_pdf(report):
    """Return the report as PDF bytes."""
    styles = _styles()
    buffer = BytesIO()
    student_name = (report.data.get('student') or {}).get('name') or report.student.username
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f'{student_name} — {report.label} progress report',
        author='Wizards Learning Hub',
    )

    school_line = report.school.name if report.school_id else 'Individual learner'
    flow = [
        Paragraph(f'{report.get_period_type_display()} Progress Report', styles['title']),
        Paragraph(
            f'{student_name} &middot; {report.label} &middot; {school_line}<br/>'
            f'{report.period_start:%d %b %Y} – {report.period_end:%d %b %Y}',
            styles['subtitle'],
        ),
    ]

    if not report.has_activity:
        flow.append(_empty_note(styles))
        doc.build(flow)
        return buffer.getvalue()

    totals = report.totals
    flow += [
        Paragraph('At a glance', styles['heading']),
        _kpi_table(totals),
        Paragraph(
            f'Retrying moved the average from {totals.get("avg_first_pct", 0)}% '
            f'on the first attempt to {totals.get("avg_best_pct", 0)}% at best — '
            f'a gain of {totals.get("improvement_pct", 0)} percentage points.',
            styles['note'],
        ),
    ]

    awards = report.awards
    if awards:
        flow.append(Paragraph('Recognition', styles['heading']))
        flow += _awards_block(awards, styles)

    topics = report.topics
    if topics:
        flow.append(Paragraph('By topic', styles['heading']))
        chart = _topic_chart(topics)
        if chart is not None:
            flow.append(chart)
            flow.append(Paragraph(
                'Accuracy across every question answered, weakest topic first.',
                styles['caption'],
            ))
        flow.append(Spacer(1, 6))
        flow.append(_data_table(
            ['Topic', 'Answered', 'Correct', 'Accuracy'],
            [[row['topic'], row['answered'], row['correct'], f'{row["accuracy_pct"]}%']
             for row in topics],
            widths=[CONTENT_WIDTH * 0.52, CONTENT_WIDTH * 0.16,
                    CONTENT_WIDTH * 0.16, CONTENT_WIDTH * 0.16],
            aligns=['LEFT', 'CENTER', 'CENTER', 'CENTER'],
        ))

    attempts = report.attempts
    if attempts.get('items'):
        flow.append(PageBreak())
        flow.append(Paragraph('Effort and attempts', styles['heading']))
        pie = _attempts_pie(attempts.get('distribution') or [])
        if pie is not None:
            flow.append(KeepTogether([
                pie,
                Paragraph(
                    f'{attempts.get("repeat_rate_pct", 0)}% of homework was '
                    f'attempted more than once, averaging '
                    f'{attempts.get("avg_attempts", 0)} attempts each.',
                    styles['caption'],
                ),
            ]))
        flow.append(Spacer(1, 6))
        flow.append(_data_table(
            ['Homework', 'Attempts', 'First', 'Best', 'Gain'],
            [[row['title'], row['attempts'], f'{row["first_pct"]}%',
              f'{row["best_pct"]}%', f'{row["gain_pct"]:+d} pts']
             for row in attempts['items']],
            widths=[CONTENT_WIDTH * 0.44, CONTENT_WIDTH * 0.13,
                    CONTENT_WIDTH * 0.13, CONTENT_WIDTH * 0.13,
                    CONTENT_WIDTH * 0.17],
            aligns=['LEFT', 'CENTER', 'CENTER', 'CENTER', 'CENTER'],
        ))

    trend = report.trend
    trend_chart = _trend_chart(trend)
    if trend_chart is not None:
        flow.append(Paragraph('Over the period', styles['heading']))
        flow.append(trend_chart)
        flow.append(Paragraph('Average score per attempt.', styles['caption']))

    worksheets = report.worksheets
    if worksheets.get('items'):
        flow.append(Paragraph('Worksheets', styles['heading']))
        flow.append(_data_table(
            ['Worksheet', 'Score', 'Result'],
            [[row['title'], f'{row["score"]}/{row["total"]}', f'{row["pct"]}%']
             for row in worksheets['items']],
            widths=[CONTENT_WIDTH * 0.6, CONTENT_WIDTH * 0.2, CONTENT_WIDTH * 0.2],
            aligns=['LEFT', 'CENTER', 'CENTER'],
        ))

    doc.build(flow, onLaterPages=_footer, onFirstPage=_footer)
    return buffer.getvalue()


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 10 * mm, 'Wizards Learning Hub')
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f'Page {doc.page}')
    canvas.restoreState()
