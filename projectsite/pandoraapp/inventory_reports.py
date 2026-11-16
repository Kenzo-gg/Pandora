"""Current inventory data shared by the page and PDF export."""
from io import BytesIO
from xml.sax.saxutils import escape

from django import forms
from django.db.models import F, Q
from django.utils import timezone

from .models import Category, Product
from .reports import MANILA
from .services import PURCHASE_ROLES, _authorize


class InventoryReportForm(forms.Form):
    q = forms.CharField(label='Product name or SKU', required=False, max_length=100)
    category = forms.ModelChoiceField(queryset=Category.objects.order_by('name', 'pk'), required=False)
    status = forms.ChoiceField(required=False, choices=[('', 'All stock statuses'),
        ('out', 'Out of stock'), ('low', 'Low stock'), ('available', 'Above reorder level')])
    active = forms.ChoiceField(choices=[('active', 'Active products'), ('all', 'All products'),
                                       ('inactive', 'Inactive products')])


def inventory_summary(*, actor, q='', category=None, status='', active='active'):
    _authorize(actor, PURCHASE_ROLES, 'view_product')
    products = Product.objects.all()
    if active != 'all':
        products = products.filter(is_active=active == 'active')
    if q:
        products = products.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    if category:
        products = products.filter(category=category)
    if status == 'out':
        products = products.filter(current_stock=0)
    elif status == 'low':
        products = products.filter(current_stock__gt=0, current_stock__lte=F('reorder_level'))
    elif status == 'available':
        products = products.filter(current_stock__gt=F('reorder_level'))
    rows = list(products.order_by('name', 'pk').values('sku', 'name', 'category__name',
        'preferred_supplier__name', 'current_stock', 'reorder_level', 'is_active'))
    for row in rows:
        row['stock_status'] = 'Above reorder level'
        if row['current_stock'] == 0:
            row['stock_status'] = 'Out of stock'
        elif row['current_stock'] <= row['reorder_level']:
            row['stock_status'] = 'Low stock'
    return {'rows': rows, 'product_count': len(rows),
            'units': sum(row['current_stock'] for row in rows),
            'filters': f"Search: {q or 'All'} | Category: {category or 'All'} | Stock: {status or 'All'} | Products: {active}",
            'generated': timezone.now().astimezone(MANILA).strftime('%Y-%m-%d %H:%M %Z')}


def inventory_pdf(report):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    stream = BytesIO()
    page_size = landscape(A4)
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(stream, pagesize=page_size, leftMargin=30, rightMargin=30,
                           topMargin=30, bottomMargin=40, title='Pandora Current Inventory')
    story = [Paragraph('Pandora | Current inventory', styles['Title']),
             Paragraph('Current stock at generation time | Asia/Manila', styles['Normal']),
             Paragraph('Generated ' + report['generated'], styles['Normal']),
             Paragraph(escape(report['filters']), styles['Normal']),
             Paragraph(f"Products: {report['product_count']} | Total units: {report['units']}", styles['Normal']),
             Spacer(1, 16)]
    data = [['SKU', 'Product', 'Category', 'Preferred supplier', 'Quantity', 'Reorder', 'Status', 'Active']]
    for row in report['rows']:
        data.append([Paragraph(escape(str(value)), styles['Normal']) for value in [
            row['sku'], row['name'], row['category__name'], row['preferred_supplier__name'] or '-',
            row['current_stock'], row['reorder_level'], row['stock_status'], 'Yes' if row['is_active'] else 'No']])
    if not report['rows']:
        story.append(Paragraph('No products match these filters.', styles['Normal']))
    table = Table(data, colWidths=[75, 145, 100, 115, 55, 55, 90, 45], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LINEBELOW', (0, 0), (-1, -1), .3, colors.HexColor('#cbd5e1')),
    ]))
    story.append(table)

    def footer(canvas, document):
        canvas.setFont('Helvetica', 9)
        canvas.drawRightString(page_size[0] - 30, 22, f'Pandora | Page {document.page}')

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
