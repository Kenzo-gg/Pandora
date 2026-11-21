from django import template
from ..navigation import access_for

register = template.Library()


@register.simple_tag
def workspace_access(user):
    return access_for(user) if user.is_authenticated else {}


@register.simple_tag(takes_context=True)
def navigation(context, access):
    request = context['request']
    if not request.user.is_authenticated:
        return []
    links = [
        ('Main', 'home', 'Dashboard', 'dashboard', None),
        ('Main', 'sale_history', 'Sales', 'receipt', 'sale_history_access'),
        ('Main', 'products', 'Products', 'package', 'catalog_access'),
        ('Main', 'inventory_report', 'Inventory', 'warehouse', 'inventory_access'),
        ('Main', 'purchase_history', 'Purchases', 'cart', 'purchase_history_access'),
        ('Main', 'suppliers', 'Suppliers', 'truck', 'supplier_access'),
        ('Management', 'reorder', 'Reorder report', 'alert', 'inventory_access'),
        ('Management', 'movement_report', 'Stock movements', 'transfer', 'inventory_access'),
        ('Management', 'sales_report', 'Sales summary', 'bars', 'financial_access'),
        ('Management', 'profit_report', 'Profit and loss', 'balance', 'financial_access'),
        ('Management', 'performance_report', 'Product performance', 'trend', 'financial_access'),
        ('Management', 'expenses', 'Operating expenses', 'wallet', 'expense_access'),
    ]
    return [(group, 'pandoraapp:' + route, label, icon) for group, route, label, icon, permission
            in links if permission is None or access[permission]]
