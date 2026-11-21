"""Product and category management screens for Admin and Inventory Staff.

Stock and average cost are never edited here: they change only when purchases are received
and sales are completed, through services.py.
"""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from . import services
from .models import Category, Product, Supplier


def _authorize(user, permission):
    return services._authorize(user, services.PURCHASE_ROLES, permission)


def product_history(product):
    """Counts of records that keep a product in the books; any of them blocks deletion."""
    return {
        'purchase lines': product.purchase_items.count(),
        'sale lines': product.sale_items.count(),
        'stock movements': product.stock_movements.count(),
    }


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['sku', 'name', 'category', 'brand', 'model', 'preferred_supplier', 'selling_price',
                  'reorder_level', 'warranty_months', 'description', 'is_active']
        labels = {'sku': 'SKU (product code)', 'selling_price': 'Selling price (₱)',
                  'reorder_level': 'Reorder level (alert at or below)',
                  'warranty_months': 'Warranty (months)', 'is_active': 'Active (available for sale and purchase)'}
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.order_by('name')
        suppliers = Supplier.objects.filter(is_active=True)
        current = getattr(self.instance, 'preferred_supplier_id', None)
        if current:  # keep a retired supplier selectable on products that already use it
            suppliers = Supplier.objects.filter(Q(is_active=True) | Q(pk=current))
        self.fields['preferred_supplier'].queryset = suppliers.order_by('name')
        self.fields['preferred_supplier'].empty_label = 'No preferred supplier'

    def clean_sku(self):
        sku = self.cleaned_data['sku'].strip().upper()
        if not sku:
            raise forms.ValidationError('Enter a SKU.')
        return sku


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'description']
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        clash = Category.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError('A category with this name already exists.')
        return name


@login_required(login_url='/login/')
@require_http_methods(['GET', 'POST'])
def product_edit(request, pk=None):
    product = get_object_or_404(Product, pk=pk) if pk else None
    user = _authorize(request.user, 'change_product' if product else 'add_product')
    form = ProductForm(request.POST or None, instance=product)
    if request.method == 'POST' and form.is_valid():
        saved = form.save()
        messages.success(request, f'{saved.name} {"updated" if product else "added"}.')
        return redirect('pandoraapp:product_edit', pk=saved.pk)
    history = product_history(product) if product else None
    return render(request, 'pandoraapp/product_form.html', {
        'form': form, 'product': product, 'history': history,
        'has_history': bool(history and any(history.values())),
        'can_delete': bool(product) and user.has_perm('pandoraapp.delete_product')})


@login_required(login_url='/login/')
@require_http_methods(['POST'])
def product_remove(request, pk):
    """Delete a product that was never used; otherwise deactivate it so its history stays intact."""
    with transaction.atomic():
        product = get_object_or_404(Product.objects.select_for_update(), pk=pk)
        if any(product_history(product).values()):
            _authorize(request.user, 'change_product')
            if product.is_active:
                product.is_active = False
                product.save(update_fields=['is_active', 'updated_at'])
            messages.success(request, f'{product.name} was deactivated. It has transaction history, '
                             'so it is kept for past records but hidden from new sales and purchases.')
            return redirect('pandoraapp:product_edit', pk=product.pk)
        _authorize(request.user, 'delete_product')
        name = product.name
        product.delete()
    messages.success(request, f'{name} was deleted. It had no sales, purchases or stock movements.')
    return redirect('pandoraapp:products')


@login_required(login_url='/login/')
@require_GET
def category_list(request):
    user = _authorize(request.user, 'view_category')
    rows = Category.objects.annotate(
        active_count=Count('products', filter=Q(products__is_active=True)),
        total_count=Count('products')).order_by('name')
    return render(request, 'pandoraapp/categories.html', {
        'rows': rows, 'can_add': user.has_perm('pandoraapp.add_category'),
        'can_edit': user.has_perm('pandoraapp.change_category'),
        'can_delete': user.has_perm('pandoraapp.delete_category')})


@login_required(login_url='/login/')
@require_http_methods(['GET', 'POST'])
def category_edit(request, pk=None):
    category = get_object_or_404(Category, pk=pk) if pk else None
    _authorize(request.user, 'change_category' if category else 'add_category')
    form = CategoryForm(request.POST or None, instance=category)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Category {"updated" if category else "added"}.')
        return redirect('pandoraapp:categories')
    return render(request, 'pandoraapp/simple_form.html', {
        'form': form, 'title': f'Edit {category.name}' if category else 'Add category',
        'button': 'Save category'})


@login_required(login_url='/login/')
@require_http_methods(['POST'])
def category_delete(request, pk):
    _authorize(request.user, 'delete_category')
    with transaction.atomic():
        category = get_object_or_404(Category.objects.select_for_update(), pk=pk)
        if category.products.exists():
            messages.error(request, f'{category.name} still has products, so it cannot be deleted. '
                           'Move or delete those products first.')
        else:
            category.delete()
            messages.success(request, f'Category {category.name} deleted.')
    return redirect('pandoraapp:categories')
