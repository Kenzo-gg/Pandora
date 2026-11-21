from datetime import datetime, time, timedelta
from decimal import Decimal

from django import forms
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Category, OperatingExpense, Product, SaleItem, StockMovement
from .reports import MANILA, SalesReportForm
from .services import PURCHASE_ROLES, _authorize


class PeriodForm(SalesReportForm):
    period = None
    category = forms.ModelChoiceField(queryset=Category.objects.order_by('name', 'pk'), required=False,
                                      empty_label='All categories')


class PerformanceForm(PeriodForm):
    fast = forms.IntegerField(label='Fast-selling minimum units', min_value=1, max_value=2147483647)
    slow = forms.IntegerField(label='Slow-selling maximum units', min_value=0, max_value=2147483646)

    def clean(self):
        data = super().clean()
        if data.get('fast') is not None and data.get('slow') is not None and data['slow'] >= data['fast']:
            raise forms.ValidationError('Slow-selling maximum must be below the fast-selling minimum.')
        return data


def report_notes(start, end, category):
    return [f'{start} to {end} inclusive | Business dates Asia/Manila | Currency PHP',
            f'Category: {category or "All"}',
            'Generated ' + timezone.now().astimezone(MANILA).strftime('%Y-%m-%d %H:%M %Z')]


@transaction.atomic
def performance(*, actor, start, end, category=None, fast=10, slow=2):
    _authorize(actor, {'Admin'}, 'view_sale')
    products = Product.objects.filter(Q(is_active=True) | Q(sale_items__sale__status='completed',
        sale_items__sale__sale_date__range=(start, end))).distinct()
    if category:
        products = products.filter(category=category)
    rows = {}
    for product in products.order_by('name', 'pk').values('pk', 'sku', 'name'):
        rows[product['pk']] = {'sku': product['sku'], 'name': product['name'], 'units': 0}
    items = SaleItem.objects.filter(sale__status='completed', sale__sale_date__range=(start, end))
    if category:
        items = items.filter(product__category=category)
    for item in items.values('product_id', 'quantity'):
        rows[item['product_id']]['units'] += item['quantity']
    result = []
    for row in rows.values():
        label = 'Normal'
        if row['units'] >= fast:
            label = 'Fast-selling'
        elif row['units'] <= slow:
            label = 'Slow-selling'
        result.append([row['sku'], row['name'], row['units'], label])
    return {'title': 'Fast/slow-selling products', 'headings': ['SKU', 'Product', 'Units sold', 'Classification'],
            'rows': result, 'widths': [100, 350, 100, 170],
            'notes': report_notes(start, end, category) + [
                f'Demo thresholds: fast >= {fast} units; slow <= {slow} units; other counts normal.',
                'Includes active products with zero sales and inactive products sold in the period.']}


@transaction.atomic
def profit_loss(*, actor, start, end, category=None):
    _authorize(actor, {'Admin'}, 'view_sale')
    items = SaleItem.objects.filter(sale__status='completed', sale__sale_date__range=(start, end))
    if category:
        items = items.filter(product__category=category)
    revenue = Decimal('0.00')
    cogs = Decimal('0.000000')
    for item in items.values('quantity', 'unit_price', 'unit_cost_at_sale'):
        revenue += item['quantity'] * item['unit_price']
        cogs += item['quantity'] * item['unit_cost_at_sale']
    gross = revenue - cogs
    rows = [['Revenue', f'{revenue:,.2f}'], ['Historical cost of goods sold', f'{cogs:,.2f}'],
            ['Gross profit', f'{gross:,.2f}']]
    summary = [('Revenue', revenue, 'money'), ('Gross profit', gross, 'money'),
               ('Gross margin', round(gross * 100 / revenue, 1) if revenue else None, 'percent')]
    notes = report_notes(start, end, category)
    if category:
        notes.append('Category summary includes revenue, COGS and gross profit. General expenses are unallocated.')
    else:
        expenses = list(OperatingExpense.objects.filter(expense_date__range=(start, end),
            voided_at__isnull=True).values_list('amount', flat=True))
        total = sum(expenses, Decimal('0.00'))
        rows += [['Recorded operating expenses', f'{total:,.2f}'], ['Operating profit/loss', f'{gross - total:,.2f}']]
        summary.append(('Operating profit/loss', gross - total, 'money'))
        if not expenses:
            notes.append('No nonvoided expenses are recorded for this period. Expense coverage is limited to recorded entries.')
    notes.append('Basic operating summary based on completed sales, saved costs and recorded expenses. Amounts rounded to PHP 0.01 for display.')
    return {'title': 'Basic profit/loss' if not category else 'Category gross profit',
            'headings': ['Measure', 'Amount (PHP)'], 'rows': rows, 'notes': notes, 'widths': [450, 270],
            'summary': summary}


def stock_movements(*, actor, start, end, category=None):
    _authorize(actor, PURCHASE_ROLES, 'view_product')
    beginning = datetime.combine(start, time.min, tzinfo=MANILA)
    finish = datetime.combine(end, time.max, tzinfo=MANILA)
    query = StockMovement.objects.filter(created_at__gte=beginning, created_at__lte=finish)
    if category:
        query = query.filter(product__category=category)
    rows = []
    for entry in query.select_related('product', 'performed_by_auth', 'sale_item__sale', 'purchase_item__purchase').order_by('created_at', 'pk'):
        reference = 'Adjustment'
        if entry.sale_item_id:
            reference = entry.sale_item.sale.receipt_no
        elif entry.purchase_item_id:
            reference = entry.purchase_item.purchase.reference_no
        rows.append([entry.created_at.astimezone(MANILA).strftime('%Y-%m-%d %H:%M'), entry.product.sku,
            entry.product.name, entry.get_movement_type_display(), entry.quantity_change,
            entry.stock_after, reference, entry.performed_by_auth.get_username()])
    return {'title': 'Stock movement sheet', 'headings': ['Time (Manila)', 'SKU', 'Product', 'Type', 'Change', 'Balance after', 'Reference', 'Operator'],
            'rows': rows, 'notes': report_notes(start, end, category) + ['Recorded stock movements in timestamp order.'],
            'widths': [85, 65, 110, 60, 55, 55, 180, 110]}
