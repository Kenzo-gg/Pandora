"""Conservative admin until the tested transaction services/screens are available.
Posted records, movements and legacy identities are never edited here.
"""
from django.contrib import admin
from .models import (
    Category, Product, Supplier, AuthorizedUser, AuthorizedGroup,
    AuthorizedUserGroup, Purchase, PurchaseItem, Sale, SaleItem, StockMovement,
    ExpenseCategory, OperatingExpense,
)


def financial_user(request):
    user = request.user
    return user.is_active and user.is_staff and (
        user.is_superuser or user.groups.filter(name='Admin').exists())


class ReadOnlyAdmin(admin.ModelAdmin):
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)


class FinancialReadOnlyAdmin(ReadOnlyAdmin):
    def has_view_permission(self, request, obj=None):
        return financial_user(request) and super().has_view_permission(request, obj)

    def has_module_permission(self, request):
        return financial_user(request) and super().has_module_permission(request)


class LegacyAdmin(ReadOnlyAdmin):
    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_module_permission(self, request):
        return self.has_view_permission(request)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('sku', 'name', 'brand', 'category', 'preferred_supplier',
                    'selling_price', 'current_stock', 'reorder_level', 'is_active')
    list_filter = ('category', 'brand', 'is_active')
    search_fields = ('sku', 'name', 'brand', 'model')
    readonly_fields = ('current_stock', 'cost_price')
    # Cashier access belongs in a selling-catalog screen, not this cost-bearing form.
    def has_view_permission(self, request, obj=None):
        return (financial_user(request) or request.user.has_perm('pandoraapp.change_product')) and super().has_view_permission(request, obj)

    def has_module_permission(self, request):
        return self.has_view_permission(request)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_person', 'contact_number', 'email', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'contact_person', 'email')


@admin.register(Purchase)
class PurchaseAdmin(ReadOnlyAdmin):
    list_display = ('reference_no', 'supplier', 'created_by_auth', 'order_date', 'status', 'total_cost')
    list_filter = ('status', 'supplier')
    search_fields = ('reference_no',)


@admin.register(PurchaseItem)
class PurchaseItemAdmin(ReadOnlyAdmin):
    list_display = ('purchase', 'product', 'quantity', 'unit_cost')


@admin.register(Sale)
class SaleAdmin(FinancialReadOnlyAdmin):
    list_display = ('receipt_no', 'cashier_auth', 'sale_date', 'status', 'payment_method', 'total_amount')
    list_filter = ('status', 'payment_method')
    search_fields = ('receipt_no',)


@admin.register(SaleItem)
class SaleItemAdmin(FinancialReadOnlyAdmin):
    list_display = ('sale', 'product', 'quantity', 'unit_price', 'unit_cost_at_sale')


@admin.register(StockMovement)
class StockMovementAdmin(ReadOnlyAdmin):
    list_display = ('product', 'movement_type', 'quantity_change', 'stock_after', 'performed_by_auth')
    list_filter = ('movement_type',)


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

    def has_module_permission(self, request):
        return financial_user(request) and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return financial_user(request) and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return financial_user(request) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return financial_user(request) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return financial_user(request) and super().has_delete_permission(request, obj)


@admin.register(OperatingExpense)
class OperatingExpenseAdmin(FinancialReadOnlyAdmin):
    list_display = ('expense_date', 'category', 'description', 'amount', 'created_by', 'voided_at')
    list_filter = ('category', 'expense_date')


admin.site.register(AuthorizedUser, LegacyAdmin)
admin.site.register(AuthorizedGroup, LegacyAdmin)
admin.site.register(AuthorizedUserGroup, LegacyAdmin)
