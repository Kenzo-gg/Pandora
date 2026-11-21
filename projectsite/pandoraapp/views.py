from datetime import date, timedelta
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponseBadRequest
from django.http import HttpResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .navigation import access_for
from .product_filters import ProductFilterForm
from . import services
from .forms import (CancellationForm, ConfirmationForm, PaymentForm, PurchaseHeaderForm,
                    PurchaseLines, SaleHeaderForm, SaleLines)
from .models import OperatingExpense, Product, Purchase, Sale, SaleItem, Supplier
from .stock_queries import products_needing_reorder, reorder_report
from .reports import MANILA, SalesReportForm, sales_pdf, sales_summary
from .inventory_reports import InventoryReportForm, inventory_pdf, inventory_summary

TOKEN_SALT = 'pandora.transaction.confirmation.v1'


@login_required(login_url='/login/')
@require_GET
def inventory_report(request):
    services._authorize(request.user, services.PURCHASE_ROLES, 'view_product')
    data = request.GET.copy()
    if 'active' not in data:
        data['active'] = 'active'
    form = InventoryReportForm(data)
    report = None
    if form.is_valid():
        report = inventory_summary(actor=request.user, **form.cleaned_data)
        if request.GET.get('format') == 'pdf':
            response = HttpResponse(inventory_pdf(report), content_type='application/pdf')
            response['Content-Disposition'] = 'attachment; filename="pandora-current-inventory.pdf"'
            response['Cache-Control'] = 'private, no-store'
            return response
    response = render(request, 'pandoraapp/inventory_report.html', {'form': form, 'report': report})
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required(login_url='/login/')
@require_GET
def sales_report(request):
    services._authorize(request.user, {'Admin'}, 'view_sale')
    today = timezone.now().astimezone(MANILA).date()
    data = {'start': today.replace(day=1), 'end': today, 'period': 'daily'}
    for key in data:
        if key in request.GET:
            data[key] = request.GET[key]
    form = SalesReportForm(data)
    report = None
    if form.is_valid():
        report = sales_summary(actor=request.user, **form.cleaned_data)
        if request.GET.get('format') == 'pdf':
            response = HttpResponse(sales_pdf(report), content_type='application/pdf')
            response['Content-Disposition'] = 'attachment; filename="pandora-sales-summary.pdf"'
            response['Cache-Control'] = 'private, no-store'
            return response
    response = render(request, 'pandoraapp/sales_report.html', {'form': form, 'report': report})
    response['Cache-Control'] = 'private, no-store'
    return response


def authorize(user, kind, permission):
    roles = services.PURCHASE_ROLES if kind == 'purchase' else services.SALE_ROLES
    return services._authorize(user, roles, permission)


def document(user, kind, pk, *, lock=False):
    model = Purchase if kind == 'purchase' else Sale
    query = model.objects.all()
    if lock:
        query = query.select_for_update()
    obj = get_object_or_404(query, pk=pk)
    if kind == 'sale':
        services._sale_owner(user, obj)
    return obj


@login_required(login_url='/login/')
@require_GET
def home(request):
    context = access_for(request.user)
    today = timezone.now().astimezone(MANILA).date()
    context['today'] = today
    month = (today.replace(day=1), today)
    cards = []
    other_cards = []
    recent = []
    if context['financial_access']:
        completed = Sale.objects.filter(status='completed')
        periods = {'7D': 7, '30D': 30, '3M': 90, '1Y': 365}
        period = request.GET.get('period', '7D')
        if period not in periods:
            period = '7D'
        context.update(period=period, periods=periods)
        start = today - timedelta(days=periods[period] - 1)
        daily = dict(completed.filter(sale_date__range=(start, today)).values('sale_date')
                     .annotate(total=Sum('total_amount')).values_list('sale_date', 'total'))
        context['days'] = [(start + timedelta(days=i), daily.get(start + timedelta(days=i), 0))
                           for i in range(periods[period])]
        sales = completed.filter(sale_date__range=(start, today))
        revenue = sum(daily.values())
        cards.extend([('Completed sales', sales.count(), False, 'Transactions in this period', 'receipt'),
                      ('Total revenue', revenue, True, 'Completed sales in this period', 'trend')])
        context.update(start=start, revenue=revenue)
        # Keep long ranges legible by grouping adjacent days into at most ten bars.
        step = (periods[period] + 9) // 10
        buckets = []
        for offset in range(0, periods[period], step):
            chunk = context['days'][offset:offset + step]
            buckets.append((chunk[0][0], chunk[-1][0], sum(amount for _, amount in chunk)))
        context.update(buckets=buckets, peak=max(row[2] for row in buckets) or 1)
        context['top_products'] = (SaleItem.objects.filter(sale__status='completed', sale__sale_date__range=(start, today))
                                   .values('product_id', 'product__name').annotate(units=Sum('quantity'))
                                   .order_by('-units', 'product_id')[:4])
    if context['purchase_history_access']:
        purchases = Purchase.objects.filter(status='completed', order_date__range=month)
        other_cards.append(('Purchases this month', purchases.aggregate(value=Sum('total_cost'))['value'] or 0, True))
        for row in Purchase.objects.order_by('-created_at', '-pk')[:5]:
            recent.append((row.created_at, row.reference_no, 'Purchase', row.get_status_display(), row.total_cost, row.pk))
    if context['sale_history_access']:
        rows = Sale.objects.all() if context['admin_access'] else Sale.objects.filter(cashier_auth=request.user)
        for row in rows.order_by('-created_at', '-pk')[:5]:
            recent.append((row.created_at, row.receipt_no, 'Sale', row.get_status_display(), row.total_amount, row.pk))
    if context['inventory_access']:
        products = Product.objects.filter(is_active=True)
        counts = products.aggregate(total=Count('pk'), out=Count('pk', filter=Q(current_stock=0)),
                                    low=Count('pk', filter=Q(current_stock__gt=0, current_stock__lte=F('reorder_level'))))
        total, low, out = counts['total'], counts['low'], counts['out']
        context.update(product_count=total, low_count=low, out_count=out, available_count=total-low-out,
                       available_end=round(100*(total-low-out)/total) if total else 0,
                       low_end=round(100*(total-out)/total) if total else 0)
        if not context['financial_access']:
            cards.append(('Active products', total, False, 'Current catalog', 'package'))
        if context['financial_access']:
            value = products.aggregate(total=Sum(F('current_stock') * F('cost_price')))['total']
            cards.append(('Inventory value', value or 0, True, 'Active stock at cost', 'package'))
        context['inventory_rows'] = products.select_related('category').order_by('name', 'pk')[:8]
        context['alerts'] = products_needing_reorder()[:4]
        other_cards.append(('Products to reorder', products_needing_reorder().count(), False))
    if context['expense_access']:
        expenses = OperatingExpense.objects.filter(voided_at__isnull=True, expense_date__range=month)
        other_cards.append(('Expenses this month', expenses.aggregate(value=Sum('amount'))['value'] or 0, True))
    context.update(cards=cards, other_cards=other_cards, recent=sorted(recent, key=lambda row: row[0], reverse=True)[:5])
    return render(request, 'pandoraapp/home.html', context)


@login_required(login_url='/login/')
@require_http_methods(['GET', 'POST'])
def create(request, kind):
    authorize(request.user, kind, 'add_' + kind)
    header_class = PurchaseHeaderForm if kind == 'purchase' else SaleHeaderForm
    lines_class = PurchaseLines if kind == 'purchase' else SaleLines
    data = request.POST if request.method == 'POST' else None
    initial = {'reference': uuid4().hex.upper()}
    if kind == 'purchase' and request.GET.get('supplier', '').isdigit():
        initial['supplier'] = int(request.GET['supplier'])
    header = header_class(data, initial=initial)
    lines = lines_class(data, prefix='items')
    header_valid = header.is_valid() if data is not None else False
    lines_valid = lines.is_valid() if data is not None else False
    if header_valid and lines_valid:
        items = []
        for row in lines.cleaned_data:
            if not row:
                continue
            item = {'product_id': row['product'].pk, 'quantity': row['quantity']}
            if kind == 'purchase':
                item['unit_cost'] = row['unit_cost']
            items.append(item)
        try:
            if kind == 'purchase':
                obj = services.create_purchase_draft(actor=request.user,
                    reference_no=header.cleaned_data['reference'],
                    supplier_id=header.cleaned_data['supplier'].pk,
                    order_date=header.cleaned_data['date'], lines=items)
            else:
                obj = services.create_sale_draft(actor=request.user,
                    receipt_no=header.cleaned_data['reference'],
                    sale_date=header.cleaned_data['date'], lines=items)
            messages.success(request, f'{kind.title()} draft saved.')
            return redirect('pandoraapp:' + kind + '_detail', pk=obj.pk)
        except services.StockError as exc:
            header.add_error(None, exc)
    return render(request, 'pandoraapp/create.html',
                  {'kind': kind, 'header': header, 'lines': lines})


def render_detail(request, kind, pk, *, action_form=None, cancel_form=None):
    authorize(request.user, kind, 'change_' + kind)
    with transaction.atomic():
        obj = document(request.user, kind, pk, lock=True)
        snapshot_function = services.purchase_snapshot if kind == 'purchase' else services.sale_snapshot
        snapshot = snapshot_function(actor=request.user, **{kind + '_id': pk})
        rows = []
        for item in obj.items.select_related('product').order_by('pk'):
            price = item.unit_cost if kind == 'purchase' else item.unit_price
            rows.append({'product': item.product.name, 'quantity': item.quantity,
                         'price': price, 'total': price * item.quantity})
        token = signing.dumps({'kind': kind, 'pk': pk, 'user': request.user.pk,
                               'lines': snapshot}, salt=TOKEN_SALT)
        form_class = ConfirmationForm if kind == 'purchase' else PaymentForm
        context = {'kind': kind, 'obj': obj, 'rows': rows,
                   'reference': obj.reference_no if kind == 'purchase' else obj.receipt_no,
                   'total': obj.total_cost if kind == 'purchase' else obj.total_amount,
                   'action_form': action_form if action_form is not None else form_class(initial={'token': token}),
                   'cancel_form': cancel_form if cancel_form is not None else CancellationForm()}
        # Render while the header lock keeps the reviewed lines consistent.
        return render(request, 'pandoraapp/detail.html', context)


@login_required(login_url='/login/')
@require_GET
def detail(request, kind, pk):
    return render_detail(request, kind, pk)


@login_required(login_url='/login/')
@require_POST
def post_transaction(request, kind, pk):
    authorize(request.user, kind, 'change_' + kind)
    document(request.user, kind, pk)
    form_class = ConfirmationForm if kind == 'purchase' else PaymentForm
    form = form_class(request.POST)
    if form.is_valid():
        try:
            payload = signing.loads(form.cleaned_data['token'], salt=TOKEN_SALT, max_age=1800)
            if (payload.get('kind'), payload.get('pk'), payload.get('user')) != (kind, pk, request.user.pk):
                raise signing.BadSignature()
            arguments = {'actor': request.user, kind + '_id': pk, 'expected_lines': payload['lines']}
            if kind == 'purchase':
                services.receive_purchase(**arguments)
            else:
                services.complete_sale(**arguments, payment_method=form.cleaned_data['payment_method'],
                                       amount_paid=form.cleaned_data['amount_paid'])
            messages.success(request, 'Purchase received.' if kind == 'purchase' else 'Sale completed.')
            return redirect('pandoraapp:' + kind + '_detail', pk=pk)
        except (signing.BadSignature, KeyError, TypeError, AttributeError):
            form.add_error(None, 'Confirmation expired or invalid. Reload and review this transaction.')
        except services.StockError as exc:
            form.add_error(None, exc)
    return render_detail(request, kind, pk, action_form=form)


@login_required(login_url='/login/')
@require_POST
def cancel(request, kind, pk):
    authorize(request.user, kind, 'change_' + kind)
    document(request.user, kind, pk)
    form = CancellationForm(request.POST)
    if form.is_valid():
        function = services.cancel_purchase if kind == 'purchase' else services.cancel_sale
        try:
            function(actor=request.user, **{kind + '_id': pk}, reason=form.cleaned_data['reason'])
            messages.success(request, f'{kind.title()} cancelled.')
            return redirect('pandoraapp:' + kind + '_detail', pk=pk)
        except services.StockError as exc:
            form.add_error(None, exc)
    return render_detail(request, kind, pk, cancel_form=form)


@login_required(login_url='/login/')
@require_GET
def reorder(request):
    return render(request, 'pandoraapp/reorder.html', {'rows': reorder_report(actor=request.user)})


@login_required(login_url='/login/')
@require_GET
def products(request):
    # Cashiers use their existing sale permission to read the selling catalog.
    if request.user.groups.filter(name='Cashier').exists() and not request.user.is_superuser:
        services._authorize(request.user, services.SALE_ROLES, 'change_sale')
    else:
        services._authorize(request.user, services.PURCHASE_ROLES, 'view_product')
    form = ProductFilterForm(request.GET)
    rows = Product.objects.filter(is_active=True)
    if form.is_valid():
        filters = form.cleaned_data
        query = filters['q']
        if query:
            rows = rows.filter(Q(name__icontains=query) | Q(sku__icontains=query)
                               | Q(brand__icontains=query) | Q(category__name__icontains=query))
        if filters['category']:
            rows = rows.filter(category=filters['category'])
        if filters['brand']:
            rows = rows.filter(brand=filters['brand'])
        if filters['stock'] == 'available':
            rows = rows.filter(current_stock__gt=0)
        elif filters['stock'] == 'low':
            rows = rows.filter(current_stock__gt=0, current_stock__lte=F('reorder_level'))
        elif filters['stock'] == 'out':
            rows = rows.filter(current_stock=0)
        if filters['min_price'] is not None:
            rows = rows.filter(selling_price__gte=filters['min_price'])
        if filters['max_price'] is not None:
            rows = rows.filter(selling_price__lte=filters['max_price'])
    else:
        rows = rows.none()
    # Project only selling-catalog fields so costs never enter the response context.
    rows = rows.order_by('name', 'pk').values('sku', 'name', 'brand', 'category__name',
                                            'selling_price', 'current_stock')
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'pandoraapp/products.html', {
        'page': Paginator(rows, 25).get_page(request.GET.get('page')),
        'filter_form': form, 'filter_query': params.urlencode()})


@login_required(login_url='/login/')
@require_GET
def history(request, kind):
    user = authorize(request.user, kind, 'change_' + kind)
    model = Purchase if kind == 'purchase' else Sale
    rows = model.objects.all()
    if kind == 'sale' and not user.is_superuser and not user.groups.filter(name='Admin').exists():
        rows = rows.filter(cashier_auth=user)
    query = request.GET.get('q', '').strip()[:100]
    status = request.GET.get('status', '')
    if status in {'pending', 'completed', 'cancelled'}:
        rows = rows.filter(status=status)
    else:
        status = ''
    if query:
        field = 'reference_no' if kind == 'purchase' else 'receipt_no'
        rows = rows.filter(**{field + '__icontains': query})
    supplier = None
    suppliers = []
    if kind == 'purchase':
        suppliers = Supplier.objects.order_by('-is_active', 'name')
        supplier_id = request.GET.get('supplier', '')
        if supplier_id.isdigit():
            supplier = Supplier.objects.filter(pk=int(supplier_id)).first()
        if supplier:
            rows = rows.filter(supplier=supplier)
        rows = rows.select_related('supplier')
    date_field = 'order_date' if kind == 'purchase' else 'sale_date'
    dates = {}
    for key, lookup in (('start', '__gte'), ('end', '__lte')):
        try:
            dates[key] = date.fromisoformat(request.GET.get(key, ''))
        except ValueError:
            dates[key] = None
        if dates[key]:
            rows = rows.filter(**{date_field + lookup: dates[key]})
    rows = rows.order_by('-created_at', '-pk')
    return render(request, 'pandoraapp/history.html', {
        'kind': kind, 'page': Paginator(rows, 25).get_page(request.GET.get('page')),
        'q': query, 'status': status, 'start': dates['start'], 'end': dates['end'],
        'supplier': supplier, 'suppliers': suppliers})
