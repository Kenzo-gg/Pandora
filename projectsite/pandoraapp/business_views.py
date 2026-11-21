from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import business_reports
from .expense_services import record_expense, void_expense
from .forms import CancellationForm
from .models import ExpenseCategory, OperatingExpense
from .output_pdf import table_pdf
from .remaining_forms import ExpenseCategoryForm, ExpenseForm
from .reports import MANILA
from .services import PURCHASE_ROLES, _authorize
from .views import authorize, document


def pdf_response(report, filename):
    response = HttpResponse(table_pdf(**report), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}.pdf"'
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required(login_url='/login/')
@require_GET
def report(request, kind):
    if kind == 'movements':
        _authorize(request.user, PURCHASE_ROLES, 'view_product')
    else:
        _authorize(request.user, {'Admin'}, 'view_sale')
    today = timezone.now().astimezone(MANILA).date()
    data = {'start': today.replace(day=1), 'end': today, 'fast': 10, 'slow': 2}
    data.update(request.GET.dict())
    form_type = business_reports.PerformanceForm if kind == 'performance' else business_reports.PeriodForm
    form = form_type(data)
    result = None
    if form.is_valid():
        function = {'performance': business_reports.performance, 'profit': business_reports.profit_loss,
                    'movements': business_reports.stock_movements}[kind]
        result = function(actor=request.user, **form.cleaned_data)
        if request.GET.get('format') == 'pdf':
            return pdf_response(result, 'pandora-' + kind)
    response = render(request, 'pandoraapp/business_report.html', {
        'form': form, 'report': result, 'title': {'performance': 'Fast/slow-selling products',
        'profit': 'Basic profit/loss', 'movements': 'Stock movement sheet'}[kind]})
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required(login_url='/login/')
@require_GET
def transaction_pdf(request, kind, pk):
    authorize(request.user, kind, 'change_' + kind)
    obj = document(request.user, kind, pk)
    if obj.status != 'completed':
        return HttpResponse('Complete the transaction before printing.', status=409)
    rows = []
    for item in obj.items.select_related('product').order_by('pk'):
        price = item.unit_cost if kind == 'purchase' else item.unit_price
        rows.append([item.product.sku, item.product.name, item.quantity, f'{price:,.2f}', f'{price * item.quantity:,.2f}'])
    if kind == 'purchase':
        title = 'Stock-In Record'
        notes = [f'Reference: {obj.reference_no} | Business date: {obj.order_date}',
            f'Supplier: {obj.supplier.name}',
            f'Received by: {obj.received_by_auth.get_username()} | Received: {obj.received_at.astimezone(MANILA):%Y-%m-%d %H:%M} Asia/Manila',
            f'Total cost: PHP {obj.total_cost:,.2f}']
    else:
        title = 'Sales receipt'
        notes = [f'Receipt: {obj.receipt_no} | Business date: {obj.sale_date}',
            f'Cashier: {obj.cashier_auth.get_username()}',
            f'Total: PHP {obj.total_amount:,.2f} | Paid: PHP {obj.amount_paid:,.2f} | Change: PHP {obj.change_amount:,.2f}',
            f'Payment: {obj.get_payment_method_display()} | No tax applied for this school demo.']
    notes.append('Currency PHP | Reprint from saved transaction values')
    return pdf_response({'title': title, 'notes': notes, 'headings': ['SKU', 'Product', 'Quantity', 'Unit price (PHP)', 'Total (PHP)'],
        'rows': rows, 'widths': [100, 300, 80, 120, 120]}, f'pandora-{kind}-{pk}')


@login_required(login_url='/login/')
@require_GET
def expenses(request):
    _authorize(request.user, {'Admin'}, 'view_operatingexpense')
    rows = OperatingExpense.objects.select_related('category', 'created_by', 'voided_by').order_by('-expense_date', '-pk')
    return render(request, 'pandoraapp/expenses.html', {'page': Paginator(rows, 25).get_page(request.GET.get('page'))})


@login_required(login_url='/login/')
@require_http_methods(['GET', 'POST'])
def expense_create(request):
    _authorize(request.user, {'Admin'}, 'add_operatingexpense')
    token = signing.dumps({'user': request.user.pk, 'request_id': str(uuid4())}, salt='pandora.expense')
    form = ExpenseForm(request.POST if request.method == 'POST' else None, initial={'token': token})
    if request.method == 'POST' and form.is_valid():
        try:
            data = signing.loads(form.cleaned_data['token'], salt='pandora.expense', max_age=86400)
            if data['user'] != request.user.pk:
                raise signing.BadSignature()
            values = {key: value for key, value in form.cleaned_data.items() if key != 'token'}
            record_expense(actor=request.user, request_id=data['request_id'], **values)
            messages.success(request, 'Expense recorded.')
            return redirect('pandoraapp:expenses')
        except (signing.BadSignature, KeyError, ValueError):
            form.add_error(None, 'Expense form expired or invalid. Reload the page before entering this expense.')
        except ValidationError as exc:
            form.add_error(None, '; '.join(exc.messages))
    return render(request, 'pandoraapp/simple_form.html', {'form': form, 'title': 'Record operating expense', 'button': 'Record expense'})


@login_required(login_url='/login/')
@require_http_methods(['GET', 'POST'])
def expense_category(request):
    _authorize(request.user, {'Admin'}, 'add_expensecategory')
    form = ExpenseCategoryForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        ExpenseCategory.objects.get_or_create(name=form.cleaned_data['name'])
        messages.success(request, 'Expense category is available.')
        return redirect('pandoraapp:expense_create')
    return render(request, 'pandoraapp/simple_form.html', {'form': form, 'title': 'Add expense category', 'button': 'Save category'})


@login_required(login_url='/login/')
@require_http_methods(['GET', 'POST'])
def expense_void(request, pk):
    _authorize(request.user, {'Admin'}, 'change_operatingexpense')
    expense = get_object_or_404(OperatingExpense, pk=pk)
    form = CancellationForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        void_expense(actor=request.user, expense_id=expense.pk, reason=form.cleaned_data['reason'])
        messages.success(request, 'Expense voided.')
        return redirect('pandoraapp:expenses')
    return render(request, 'pandoraapp/simple_form.html', {'form': form,
        'title': f'Void expense #{expense.pk}', 'description': f'{expense.description} — PHP {expense.amount}', 'button': 'Void expense'})
