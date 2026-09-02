"""Render a period report to PDF (CPP-388).

ReportLab, drawing the same charts the web view shows — a PDF that dropped the
charts and kept the tables would be a downgrade the reader did not ask for, and
the parent who downloads it is often the one who never opens the web page.

Everything is read off ``PeriodReport.data``, the same frozen snapshot the HTML
template renders, so the two can never disagree.
"""

import logging
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import (
    HorizontalBarChart, VerticalBarChart,
)
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    CondPageBreak, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer,
    Table, TableStyle,
)

logger = logging.getLogger(__name__)

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

#: Bars beyond this are unreadable at A4 width. The table lists them all.
#: Rows beyond this would run past the bottom of an A4 frame. At 10pt a row,
#: forty topics is 430pt of drawing against roughly 750pt of usable frame — so
#: in practice every topic a class has fits and the cap never bites. The table
#: under the chart still lists them all, and the caption says when it does.
TOPIC_CHART_LIMIT = 40

#: One row per topic, and the gutter is measured rather than guessed.
_TOPIC_LABEL_FONT = 'Helvetica'
_TOPIC_LABEL_SIZE = 6
_TOPIC_ROW_HEIGHT = 10


def _topic_chart(topics):
    """Accuracy per topic, weakest first — mirrors the bar chart on the page.

    HORIZONTAL, and that is the point. Drawn as vertical bars, the topic names
    had to be rotated under the axis, and a rotated label runs left and down
    from its tick until it leaves the drawing and is silently cut: "Negative
    Numbers" arrived as "…ive Numbers". Shortening the text only moves the
    cliff — "Linear Relationships & Coordinate Geometry" is a real topic name
    and no rotation makes it fit. Turning the chart on its side gives every
    name a full line to itself, and the gutter is MEASURED with stringWidth
    rather than guessed, so nothing can overrun it.

    Every bar carries its own percentage. A topic scoring 0% has a bar of zero
    length, which draws nothing at all, and this chart shows the WEAKEST topics
    — so it selects exactly the bars most likely to vanish. On the report that
    raised CPP-400, ten of ten were empty. The printed figure says nought where
    a missing bar said nothing.
    """
    rows = topics[:TOPIC_CHART_LIMIT]
    if not rows:
        return None

    # Weakest first reads top-down, but a horizontal chart stacks category 0 at
    # the BOTTOM, so the order is reversed on the way in.
    rows = list(reversed(rows))
    names = [_shorten(row['topic'], 34) for row in rows]

    gutter = max(
        stringWidth(name, _TOPIC_LABEL_FONT, _TOPIC_LABEL_SIZE)
        for name in names
    ) + 6
    # A pathological name must not squeeze the bars out of existence.
    gutter = min(gutter, CONTENT_WIDTH * 0.42)

    height = 30 + _TOPIC_ROW_HEIGHT * len(rows)
    drawing = Drawing(CONTENT_WIDTH, height)
    chart = HorizontalBarChart()
    chart.x = gutter
    chart.y = 20
    # Room at the right for the "100%" label sitting past the end of its bar.
    chart.width = CONTENT_WIDTH - gutter - 26
    chart.height = height - 30
    chart.data = [[row['accuracy_pct'] for row in rows]]
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = 100
    chart.valueAxis.valueStep = 25
    chart.valueAxis.labels.fontSize = 6
    chart.categoryAxis.categoryNames = names
    chart.categoryAxis.labels.fontName = _TOPIC_LABEL_FONT
    chart.categoryAxis.labels.fontSize = _TOPIC_LABEL_SIZE
    # Right-aligned against the axis, so the names form a clean column.
    chart.categoryAxis.labels.boxAnchor = 'e'
    chart.categoryAxis.labels.dx = -3
    chart.barLabelFormat = '%d%%'
    chart.barLabels.fontSize = 6
    chart.barLabels.fontName = 'Helvetica-Bold'
    chart.barLabels.fillColor = MUTED
    chart.barLabels.nudge = 7
    chart.barLabels.boxAnchor = 'w'
    # 3 of the 10pt row, so the bar itself is 7pt — slim enough that thirty
    # topics fit a page, thick enough to read.
    chart.groupSpacing = 3
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


def _shorten(text, limit=26):
    return text if len(text) <= limit else text[:limit - 1] + '…'


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

def _kpi_table(totals, worksheets):
    cells = [
        ('Overall average', f'{totals.get("overall_avg_pct", totals.get("avg_best_pct", 0))}%'),
        ('Homework average', f'{totals.get("avg_best_pct", 0)}%'),
        ('Gained by retrying', f'{totals.get("improvement_pct", 0):+d} pts'),
        ('Activities', str(totals.get('activity_items', 0))),
        ('Homework due', f'{totals.get("completed", 0)} of {totals.get("assigned", 0)}'),
        ('Worksheets set', f'{worksheets.get("completed", 0)} of {worksheets.get("assigned", 0)}'),
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

def _readable(logo, report):
    """Whether the logo file is actually there.

    Checked before building the flowable rather than caught around it:
    reportlab opens the image lazily during doc.build(), so a try/except around
    Image() catches nothing and the failure surfaces as a 500 halfway through
    generating a parent's download. A logo row pointing at a deleted file is
    ordinary — media outlives the database it is named in.
    """
    try:
        return logo.storage.exists(logo.name)
    except Exception:
        logger.warning(
            'progress report letterhead unreadable for school %s',
            report.school_id, exc_info=True,
        )
        return False


def _logo_image(logo, report):
    """The logo as a reportlab flowable, read through the storage backend.

    NOT ``logo.path``: production media lives on DigitalOcean Spaces, and
    ``FieldFile.path`` raises NotImplementedError on S3-backed storage. That
    would have been swallowed by the surrounding except and logged, so every
    production PDF would have quietly printed the text-only letterhead while
    the page beside it showed the logo — the kind of difference nobody reports
    because each half looks deliberate.

    Reading the bytes up front also settles the laziness problem for good: the
    image is in memory before doc.build() touches it, so there is no file left
    to disappear mid-render.
    """
    try:
        with logo.storage.open(logo.name) as fh:
            data = BytesIO(fh.read())
        return Image(data, width=22 * mm, height=22 * mm, kind='proportional')
    except Exception:
        logger.warning(
            'progress report letterhead image unreadable for school %s',
            report.school_id, exc_info=True,
        )
        return None


def _letterhead_flow(report, styles):
    """The school's letterhead, as PDF flowables. Empty when it has none.

    The PDF is the copy a family keeps, so it carries the same letterhead the
    page shows rather than a plainer version of it — resolved by the same
    helper, so the two cannot disagree about which logo or address is current.

    A logo that cannot be read is skipped rather than raised: a missing or
    corrupt image file must not stop a parent downloading their child's report.
    """
    from progress.views_reports import letterhead_for

    letterhead = letterhead_for(report)
    if not letterhead:
        return []

    lines = [letterhead['name']]
    if letterhead['department']:
        lines.append(letterhead['department'])
    if letterhead['address']:
        lines.append(letterhead['address'])
    text = Paragraph('<br/>'.join(lines), styles['subtitle'])

    logo = letterhead['logo']
    if logo and _readable(logo, report):
        image = _logo_image(logo, report)
        if image is not None:
            table = Table([[image, text]], colWidths=[26 * mm, None])
            table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ]))
            return [table]

    return [text, Spacer(1, 6)]


def _next_steps_flow(report, styles):
    """The "What's next" suggestions, as flowables.

    Read from the frozen snapshot, so the download says what the page said
    even after the figures behind it have moved on. Absent when the rules had
    nothing they could honestly say.
    """
    items = ((report.data.get('next_steps') or {}).get('items')) or []
    if not items:
        return []

    labels = {'strength': 'Strength', 'focus': 'Focus', 'next': 'Next',
              'habit': 'Habit'}
    flow = [Paragraph("What's next", styles['heading'])]
    for item in items:
        label = labels.get(item.get('kind'), 'Note')
        flow.append(Paragraph(
            f'<b>{label}</b> &nbsp; {escape(item.get("text") or "")}',
            styles['note'],
        ))
    flow.append(Spacer(1, 6))
    return flow


def _manual_flow(report, styles):
    """The teacher-authored halves — assessment and comment — as flowables.

    Resolved by the same helper the page uses, so the PDF a family keeps
    cannot say something different from the page they were linked to.

    Either may be absent; an absent section is omitted, never rendered blank.
    """
    from progress.views_reports import _manual_sections

    rubric, comment = _manual_sections(report)
    flow = []

    if rubric:
        flow.append(Paragraph("Teacher's assessment", styles['heading']))
        # 'achieved' already counts Confident + Advanced — reading it as one of
        # several parts is what 500'd the page once. See _build_student_progress.
        flow.append(Paragraph(
            f'{rubric.get("achieved", 0)} of {rubric.get("total", 0)} criteria '
            'at confident or above, against this school\'s progress criteria.',
            styles['note'],
        ))
        flow.append(Spacer(1, 6))

    if comment:
        flow.append(Paragraph("Teacher's comment", styles['heading']))
        flow.append(Paragraph(_comment_html(comment.body), styles['note']))
        who = ''
        if comment.created_by:
            who = (comment.created_by.get_full_name()
                   or comment.created_by.username)
        stamp = comment.updated_at.strftime('%-d %b %Y') if comment.updated_at else ''
        if who or stamp:
            flow.append(Paragraph(
                ' · '.join(part for part in (who, stamp) if part),
                styles['caption'],
            ))
        flow.append(Spacer(1, 6))

    return flow


def _comment_html(body):
    """A teacher's markup as the minimal HTML subset reportlab understands.

    Escaped FIRST and converted after, the same order the page's
    ``teacher_markup`` filter uses: a comment is free text a teacher typed, and
    an unescaped ``<`` would either vanish or break the paragraph parser.
    """
    import re

    text = escape(body or '')
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    return text.replace('\n', '<br/>')


def _practice_flow(report, styles):
    """Practice done in a subject's own app — coding exercises and problems.

    The PDF carried no practice section at all. For a coding report that is
    most of the content, so the download read as an almost-empty document
    beside a full page: the truncation CPP-400 reports.

    Grouped by topic, as the page has been since 1.19.11, and keeping finished
    apart from marked for the same reason — an exercise scores 100 for being
    completed, which is not a mark.
    """
    practice = report.data.get('subject_practice') or {}
    flow = []

    for section in practice.get('sections') or []:
        topics = section.get('topics') or []
        if not topics:
            continue
        flow.append(Paragraph(section.get('label') or 'Practice', styles['heading']))
        flow.append(_data_table(
            ['Topic', 'Practised', 'Attempts', 'Finished', 'Best'],
            [[
                topic['name'],
                topic['items'],
                topic['attempts'],
                (f'{topic["finished"]} of {topic["exercises"]}'
                 if topic.get('exercises') else '—'),
                ('—' if topic.get('best_pct') is None else f'{topic["best_pct"]}%'),
            ] for topic in topics],
            widths=[CONTENT_WIDTH * 0.36, CONTENT_WIDTH * 0.15,
                    CONTENT_WIDTH * 0.15, CONTENT_WIDTH * 0.19,
                    CONTENT_WIDTH * 0.15],
            aligns=['LEFT', 'CENTER', 'CENTER', 'CENTER', 'CENTER'],
        ))
        flow.append(Paragraph(
            f'{section.get("items", 0)} attempted over '
            f'{section.get("attempts", 0)} attempts.',
            styles['caption'],
        ))
        flow.append(Spacer(1, 6))

    return flow


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
    flow = _letterhead_flow(report, styles) + [
        Paragraph(f'{report.get_period_type_display()} Progress Report', styles['title']),
        Paragraph(
            f'{student_name} &middot; {report.label} &middot; {school_line}<br/>'
            f'{report.period_start:%d %b %Y} – {report.period_end:%d %b %Y}',
            styles['subtitle'],
        ),
    ]

    flow += _next_steps_flow(report, styles)

    # Before the empty-report return, deliberately. A child with no
    # submissions is exactly when the teacher's assessment and comment are the
    # only things left to say — the page moved them out of this branch in
    # 1.19.1 and the PDF kept the old shape, so a parent's download lost them.
    flow += _manual_flow(report, styles)

    if not report.has_activity:
        flow.append(_empty_note(styles))
        doc.build(flow, onLaterPages=_footer, onFirstPage=_footer)
        return buffer.getvalue()

    totals = report.totals
    flow += [
        Paragraph('At a glance', styles['heading']),
        _kpi_table(totals, report.worksheets),
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
            # The chart is capped because thirty bars are unreadable, but it
            # said so nowhere — it just looked like the whole picture with
            # topics missing. The table below carries every row.
            shown = min(len(topics), TOPIC_CHART_LIMIT)
            caption = 'Accuracy across every question answered, weakest topic first.'
            if len(topics) > shown:
                caption = (
                    f'The {shown} weakest of {len(topics)} topics. '
                    'Every topic is listed in the table below.'
                )
            flow.append(Paragraph(caption, styles['caption']))
        flow.append(Spacer(1, 6))
        flow.append(_data_table(
            ['Topic', 'Answered', 'Correct', 'Accuracy'],
            [[row['topic'], row['answered'], row['correct'], f'{row["accuracy_pct"]}%']
             for row in topics],
            widths=[CONTENT_WIDTH * 0.52, CONTENT_WIDTH * 0.16,
                    CONTENT_WIDTH * 0.16, CONTENT_WIDTH * 0.16],
            aligns=['LEFT', 'CENTER', 'CENTER', 'CENTER'],
        ))

    flow += _practice_flow(report, styles)

    attempts = report.attempts
    if attempts.get('items'):
        # Enough room for the heading, the pie and its caption, or start a new
        # page — but not an unconditional break, which left half a page blank.
        flow.append(CondPageBreak(190))
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

    quizzes = report.quizzes
    if quizzes.get('items'):
        flow.append(Paragraph('Maths quizzes', styles['heading']))
        flow.append(_data_table(
            ['Topic', 'Attempts', 'First', 'Best', 'Gain'],
            [[row['name'], row['attempts'], f'{row["first_pct"]}%',
              f'{row["best_pct"]}%', f'{row["gain_pct"]:+d} pts']
             for row in quizzes['items']],
            widths=[CONTENT_WIDTH * 0.44, CONTENT_WIDTH * 0.13,
                    CONTENT_WIDTH * 0.13, CONTENT_WIDTH * 0.13,
                    CONTENT_WIDTH * 0.17],
            aligns=['LEFT', 'CENTER', 'CENTER', 'CENTER', 'CENTER'],
        ))

    times_tables = report.times_tables
    if times_tables.get('items'):
        flow.append(Paragraph('Times tables', styles['heading']))
        flow.append(_data_table(
            ['Table', 'Multiplication', 'Division'],
            [[f'{row["table"]}×',
              '—' if row['multiplication_pct'] is None else f'{row["multiplication_pct"]}%',
              '—' if row['division_pct'] is None else f'{row["division_pct"]}%']
             for row in times_tables['items']],
            widths=[CONTENT_WIDTH * 0.4, CONTENT_WIDTH * 0.3, CONTENT_WIDTH * 0.3],
            aligns=['LEFT', 'CENTER', 'CENTER'],
        ))

    basic_facts = report.basic_facts
    if basic_facts.get('items'):
        flow.append(Paragraph('Basic facts', styles['heading']))
        flow.append(_data_table(
            ['Subtopic', 'Level', 'Best'],
            [[row['subtopic'], row['level'] or '—', f'{row["best_pct"]}%']
             for row in basic_facts['items']],
            widths=[CONTENT_WIDTH * 0.5, CONTENT_WIDTH * 0.25, CONTENT_WIDTH * 0.25],
            aligns=['LEFT', 'CENTER', 'CENTER'],
        ))

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
