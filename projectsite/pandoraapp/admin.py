from django.contrib import admin
from .models import (
    Category, Product, Supplier, AuthorizedUser, AuthorizedGroup,
    AuthorizedUserGroup, Purchase, Sale, PurchaseItem, SaleItem, StockMovement,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('sku', 'name', 'brand', 'category', 'cost_price',
                    'selling_price', 'current_stock', 'reorder_level', 'is_active')
    list_filter = ('category', 'brand', 'is_active')
    search_fields = ('sku', 'name', 'brand', 'model')


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_person', 'contact_number', 'email', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'contact_person', 'email')


@admin.register(AuthorizedUser)
class AuthorizedUserAdmin(admin.ModelAdmin):
    list_display = ('username', 'first_name', 'last_name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('username', 'first_name', 'last_name')


@admin.register(AuthorizedGroup)
class AuthorizedGroupAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(AuthorizedUserGroup)
class AuthorizedUserGroupAdmin(admin.ModelAdmin):
    list_display = ('user', 'group')
    list_filter = ('group',)


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ('reference_no', 'supplier', 'created_by', 'order_date',
                    'status', 'total_cost')
    list_filter = ('status', 'supplier')
    search_fields = ('reference_no',)


@admin.register(PurchaseItem)
class PurchaseItemAdmin(admin.ModelAdmin):
    list_display = ('purchase', 'product', 'quantity', 'unit_cost', 'total_cost')

    @admin.display(description='Total cost')
    def total_cost(self, obj):
        return obj.quantity * obj.unit_cost


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ('receipt_no', 'cashier', 'sale_date', 'status',
                    'payment_method', 'total_amount')
    list_filter = ('status', 'payment_method')
    search_fields = ('receipt_no',)


@admin.register(SaleItem)
class SaleItemAdmin(admin.ModelAdmin):
    list_display = ('sale', 'product', 'quantity', 'unit_price', 'total_price')

    @admin.display(description='Total price')
    def total_price(self, obj):
        return obj.quantity * obj.unit_price


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('product', 'movement_type', 'quantity_change',
                    'stock_after', 'performed_by')
    list_filter = ('movement_type',)