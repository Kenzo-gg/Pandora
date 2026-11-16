"""Sales summaries shared by the screen and PDF export."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from django import forms
from django.db.models import Sum
from django.utils import timezone

from .models import Sale
from .services import _authorize

MANILA = ZoneInfo('Asia/Manila')


class SalesReportForm(forms.Form):
    start = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    end = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    period = forms.ChoiceField(choices=[('daily', 'Daily'), ('weekly', 'Weekly'), ('monthly', 'Monthly')])

    def clean(self):
        data = super().clean()
        if data.get('start') and data.get('end') and data['start'] > data['end']:
            raise forms.ValidationError('Start date must be on or before end date.')
        return data


def sales_summary(*, actor, start, end, period):
    _authorize(actor, {'Admin'}, 'view_sale')
    # Aggregate units per sale first to avoid multiplying header revenue by line count.
    sales = (Sale.objects.filter(status='completed', sale_date__range=(start, end))
             .annotate(units=Sum('items__quantity')).prefetch_related('items__product')
             .order_by('sale_date', 'pk'))
    buckets = defaultdict(lambda: {'transactions': 0, 'units': 0, 'revenue': Decimal('0.00')})
    products = {}
    for sale in sales:
        day = sale.sale_date
        if period == 'weekly':
            day -= timedelta(days=day.weekday())
        elif period == 'monthly':
            day = day.replace(day=1)
        row = buckets[day]
        row['transactions'] += 1
        row['units'] += sale.units or 0
        row['revenue'] += sale.total_amount
        for item in sale.items.all():
            product = products.setdefault(item.product_id, {
                'sku': item.product.sku, 'name': item.product.name,
                'units': 0, 'revenue': Decimal('0.00')})
            product['units'] += item.quantity
            product['revenue'] += item.quantity * item.unit_price
    rows = []
    for day, values in sorted(buckets.items()):
        label = day.isoformat()
        if period == 'weekly':
            label += ' to ' + (day + timedelta(days=6)).isoformat()
        elif period == 'monthly':
            label = day.strftime('%Y-%m')
        rows.append({'label': label, **values})
    totals = {key: sum((row[key] for row in rows), Decimal('0.00') if key == 'revenue' else 0)
              for key in ['transactions', 'units', 'revenue']}
    return {'rows': rows, 'products': sorted(products.values(), key=lambda row: (row['name'], row['sku'])),
            'totals': totals, 'start': start, 'end': end, 'period': period,
            'generated': timezone.now().astimezone(MANILA).strftime('%Y-%m-%d %H:%M %Z')}


def sales_pdf(report):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    stream = BytesIO()
    doc = SimpleDocTemplate(stream, pagesize=A4, title='Pandora Sales Summary',
                            leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=42)
    styles = getSampleStyleSheet()
    story = [Paragraph('Pandora | Sales summary', styles['Title']),
             Paragraph(f"{report['start']} to {report['end']} (inclusive) | {report['period'].title()}", styles['Normal']),
             Paragraph('Completed sales | Currency PHP | Business dates Asia/Manila', styles['Normal']),
             Paragraph('Generated ' + report['generated'], styles['Normal']),
             Paragraph('Weekly periods run Monday-Sunday. Totals include only selected dates.', styles['Normal']),
             Spacer(1, 18)]
    data = [['Period', 'Transactions', 'Units', 'Revenue (PHP)']]
    for row in report['rows']:
        data.append([row['label'], str(row['transactions']), str(row['units']), f"{row['revenue']:,.2f}"])
    if not report['rows']:
        story.append(Paragraph('No completed sales in this period.', styles['Normal']))
    total = report['totals']
    data.append(['Total', str(total['transactions']), str(total['units']), f"{total['revenue']:,.2f}"])
    table = Table(data, colWidths=[190, 95, 65, 173], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e2e8f0')),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 9),
        ('LINEBELOW', (0, 0), (-1, -1), .3, colors.HexColor('#cbd5e1')),
    ]))
    story.append(table)
    story.extend([Spacer(1, 20), Paragraph('Products sold', styles['Heading2'])])
    product_data = [['SKU', 'Product', 'Units', 'Revenue (PHP)']]
    for product in report['products']:
        product_data.append([
            Paragraph(escape(product['sku']), styles['Normal']),
            Paragraph(escape(product['name']), styles['Normal']),
            str(product['units']), f"{product['revenue']:,.2f}"])
    if not report['products']:
        story.append(Paragraph('No products sold in this period.', styles['Normal']))
    product_data.append(['Total', '', str(total['units']), f"{total['revenue']:,.2f}"])
    product_table = Table(product_data, colWidths=[100, 230, 50, 143], repeatRows=1)
    product_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e2e8f0')),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 9),
        ('LINEBELOW', (0, 0), (-1, -1), .3, colors.HexColor('#cbd5e1')),
    ]))
    story.append(product_table)

    def footer(canvas, document):
        canvas.setFont('Helvetica', 9)
        canvas.drawRightString(A4[0] - 36, 24, f'Pandora | Page {document.page}')

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
