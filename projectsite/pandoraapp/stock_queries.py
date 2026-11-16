"""Read-only reorder queries. Use the protected function from views."""
from django.db.models import F
from .models import Product
from .services import _authorize, PURCHASE_ROLES


def products_needing_reorder():
    """Internal query: active products at or below the reorder level."""
    return (Product.objects.filter(is_active=True, current_stock__lte=F('reorder_level'))
        .select_related('category', 'preferred_supplier').order_by('current_stock', 'sku'))


def reorder_report(*, actor):
    """Protected report for Admin/Inventory Staff; no financial fields returned."""
    _authorize(actor, PURCHASE_ROLES, 'view_product')
    return list(products_needing_reorder().values('id', 'sku', 'name', 'current_stock',
        'reorder_level', 'preferred_supplier__name'))
