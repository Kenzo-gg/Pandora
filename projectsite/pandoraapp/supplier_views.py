"""Supplier list, details with purchase history, and add/edit screens for Admin and Inventory Staff."""
from datetime import date

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from . import services
from .models import Product, Purchase, Supplier

STATUSES = {'pending', 'completed', 'cancelled'}


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ['name', 'contact_person', 'contact_number', 'email', 'address', 'is_active']
        labels = {'is_active': 'Active (can be chosen for new purchases)'}
        widgets = {'address': forms.Textarea(attrs={'rows': 3})}


def _authorize(user, permission):
    return services._authorize(user, services.PURCHASE_ROLES, permission)


def _parse_date(value):
    try:
        return date.fromisoformat(value or '')
    except ValueError:
        return None


@login_required(login_url='/login/')
@require_GET
def supplier_list(request):
    user = _authorize(request.user, 'view_supplier')
    query = request.GET.get('q', '').strip()[:100]
    status = request.GET.get('status', '')
    rows = Supplier.objects.annotate(
        completed_count=Count('purchases', filter=Q(purchases__status='completed')),
        last_order=Max('purchases__order_date'))
    if query:
        rows = rows.filter(Q(name__icontains=query) | Q(contact_person__icontains=query)
                           | Q(contact_number__icontains=query) | Q(email__icontains=query))
    if status == 'active':
        rows = rows.filter(is_active=True)
    elif status == 'inactive':
        rows = rows.filter(is_active=False)
    else:
        status = ''
    rows = rows.order_by('-is_active', 'name', 'pk')
    return render(request, 'pandoraapp/suppliers.html', {
        'page': Paginator(rows, 25).get_page(request.GET.get('page')), 'q': query, 'status': status,
        'can_add': user.has_perm('pandoraapp.add_supplier')})


@login_required(login_url='/login/')
@require_GET
def supplier_detail(request, pk):
    user = _authorize(request.user, 'view_supplier')
    supplier = get_object_or_404(Supplier, pk=pk)
    purchases = supplier.purchases.all()
    completed = purchases.filter(status='completed')
    summary = completed.aggregate(count=Count('pk'), total=Sum('total_cost'), last=Max('order_date'))
    summary['pending'] = purchases.filter(status='pending').count()

    status = request.GET.get('status', '')
    if status in STATUSES:
        purchases = purchases.filter(status=status)
    else:
        status = ''
    start, end = _parse_date(request.GET.get('start')), _parse_date(request.GET.get('end'))
    if start:
        purchases = purchases.filter(order_date__gte=start)
    if end:
        purchases = purchases.filter(order_date__lte=end)
    filtered_total = purchases.filter(status='completed').aggregate(total=Sum('total_cost'))['total']
    purchases = purchases.annotate(line_count=Count('items')).order_by('-order_date', '-pk')
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'pandoraapp/supplier_detail.html', {
        'supplier': supplier, 'summary': summary, 'status': status, 'start': start, 'end': end,
        'filtered_total': filtered_total, 'filter_query': params.urlencode(),
        'page': Paginator(purchases, 25).get_page(request.GET.get('page')),
        'products': Product.objects.filter(preferred_supplier=supplier, is_active=True).order_by('name'),
        'can_edit': user.has_perm('pandoraapp.change_supplier'),
        'can_purchase': user.has_perm('pandoraapp.add_purchase') and supplier.is_active})


@login_required(login_url='/login/')
@require_http_methods(['GET', 'POST'])
def supplier_edit(request, pk=None):
    supplier = get_object_or_404(Supplier, pk=pk) if pk else None
    _authorize(request.user, 'change_supplier' if supplier else 'add_supplier')
    form = SupplierForm(request.POST or None, instance=supplier)
    if request.method == 'POST' and form.is_valid():
        saved = form.save()
        messages.success(request, f'Supplier {"updated" if supplier else "added"}.')
        return redirect('pandoraapp:supplier_detail', pk=saved.pk)
    return render(request, 'pandoraapp/simple_form.html', {
        'form': form, 'title': f'Edit {supplier.name}' if supplier else 'Add supplier',
        'description': 'Inactive suppliers keep their purchase history but cannot be chosen for new purchases.',
        'button': 'Save supplier'})
