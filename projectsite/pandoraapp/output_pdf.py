"""Table PDF renderer for operational outputs and remaining reports."""
from io import BytesIO
from xml.sax.saxutils import escape


def table_pdf(*, title, notes, headings, rows, widths):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    size = landscape(A4)
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(title), styles['Title'])]
    story += [Paragraph(escape(str(note)), styles['Normal']) for note in notes]
    story.append(Spacer(1, 16))
    data = [[Paragraph(escape(str(value)), styles['Normal']) for value in row] for row in rows]
    if not data:
        story.append(Paragraph('No records match the selected filters.', styles['Normal']))
    header = [Paragraph('<font color="white">' + escape(str(value)) + '</font>', styles['Normal'])
              for value in headings]
    table = Table([header] + data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LINEBELOW', (0, 0), (-1, -1), .3, colors.HexColor('#cbd5e1'))]))
    story.append(table)

    def footer(canvas, document):
        canvas.setFont('Helvetica', 9)
        canvas.drawRightString(size[0] - 30, 22, f'Pandora | Page {document.page}')

    SimpleDocTemplate(buffer, pagesize=size, leftMargin=30, rightMargin=30,
        topMargin=30, bottomMargin=40, title=title).build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
