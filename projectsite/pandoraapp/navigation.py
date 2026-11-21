def access_for(user):
    groups = set(user.groups.values_list('name', flat=True))
    admin = user.is_superuser or 'Admin' in groups
    inventory = admin or 'Inventory Staff' in groups
    sales = admin or 'Cashier' in groups
    return {
        'admin_access': admin,
        'financial_access': admin and user.has_perm('pandoraapp.view_sale'),
        'expense_access': admin and user.has_perm('pandoraapp.view_operatingexpense'),
        'inventory_access': inventory and user.has_perm('pandoraapp.view_product'),
        'purchase_history_access': inventory and user.has_perm('pandoraapp.change_purchase'),
        'purchase_create_access': inventory and user.has_perm('pandoraapp.add_purchase'),
        'supplier_access': inventory and user.has_perm('pandoraapp.view_supplier'),
        'category_access': inventory and user.has_perm('pandoraapp.view_category'),
        'catalog_manage': inventory and user.has_perm('pandoraapp.change_product'),
        'sale_history_access': sales and user.has_perm('pandoraapp.change_sale'),
        'sale_create_access': sales and user.has_perm('pandoraapp.add_sale'),
        'catalog_access': (inventory and user.has_perm('pandoraapp.view_product'))
            or (sales and user.has_perm('pandoraapp.change_sale')),
    }
