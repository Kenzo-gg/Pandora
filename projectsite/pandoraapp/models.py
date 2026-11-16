from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q, F

MAX_QUANTITY = 2147483647
POSITIVE_QUANTITY = [MinValueValidator(1), MaxValueValidator(MAX_QUANTITY)]
STOCK_RANGE = [MinValueValidator(0), MaxValueValidator(MAX_QUANTITY)]
NONNEGATIVE_MONEY = [MinValueValidator(Decimal('0'))]


def check(name, condition):
    return models.CheckConstraint(name=name, condition=condition)



class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Category(BaseModel):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name


class Product(BaseModel):

    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    preferred_supplier = models.ForeignKey('Supplier', on_delete=models.PROTECT,
        null=True, blank=True, related_name='preferred_products')
    sku = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    brand = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    cost_price = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('0.000000'), validators=NONNEGATIVE_MONEY)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, validators=NONNEGATIVE_MONEY)
    current_stock = models.PositiveIntegerField(default=0, validators=STOCK_RANGE)
    reorder_level = models.PositiveIntegerField(default=0, validators=STOCK_RANGE)
    warranty_months = models.PositiveIntegerField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            check('product_money_nonnegative', Q(cost_price__gte=0, selling_price__gte=0)),
            check('product_stock_bounds', Q(current_stock__gte=0, current_stock__lte=MAX_QUANTITY,
                reorder_level__gte=0, reorder_level__lte=MAX_QUANTITY)),
            check('product_sku_not_empty', ~Q(sku='')),
        ]

    def __str__(self):
        return f"{self.name} ({self.sku})"


class Supplier(BaseModel):

    name = models.CharField(max_length=150)
    contact_person = models.CharField(max_length=150)
    contact_number = models.CharField(max_length=150)
    email = models.EmailField(max_length=254, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class AuthorizedUser(BaseModel):

    username = models.CharField(max_length=150, unique=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.username})"


class AuthorizedGroup(BaseModel):

    name = models.CharField(max_length=150, unique=True)

    def __str__(self):
        return self.name


class AuthorizedUserGroup(BaseModel):

    user = models.ForeignKey(AuthorizedUser, on_delete=models.CASCADE, related_name='user_groups')
    group = models.ForeignKey(AuthorizedGroup, on_delete=models.CASCADE, related_name='group_users')

    class Meta:
        unique_together = ('user', 'group')

    def __str__(self):
        return f"{self.user} in {self.group}"


class Purchase(BaseModel):

    reference_no = models.CharField(max_length=100, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='purchases')
    created_by = models.ForeignKey(
        AuthorizedUser, on_delete=models.PROTECT, null=True, related_name='purchases'
    )
    order_date = models.DateField()
    status = models.CharField(
        max_length=50,
        choices=[('pending', 'Pending'), ('completed', 'Completed'), ('cancelled', 'Cancelled')],
        default='pending',
    )
    received_by = models.ForeignKey(
        AuthorizedUser, on_delete=models.PROTECT, null=True, blank=True,
        related_name='received_purchases',
    )
    received_at = models.DateTimeField(blank=True, null=True)
    total_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), validators=NONNEGATIVE_MONEY)
    remarks = models.TextField(blank=True, null=True)

    # Use these Django login links for all new work. Older ID columns are retained.
    created_by_auth = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name='pandora_purchases_created')
    received_by_auth = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name='pandora_purchases_received')

    class Meta:
        indexes = [models.Index(fields=['supplier', 'order_date'], name='purchase_supplier_date')]
        constraints = [
            check('purchase_reference_not_empty', ~Q(reference_no='')),
            check('purchase_total_nonnegative', Q(total_cost__gte=0)),
            check('purchase_status_valid', Q(status__in=['pending', 'completed', 'cancelled'])),
            check('purchase_creator_required', Q(created_by_auth__isnull=False)),
            check('purchase_receipt_metadata',
                Q(status='completed', received_by_auth__isnull=False, received_at__isnull=False)
                | Q(status__in=['pending', 'cancelled'], received_by_auth__isnull=True,
                    received_at__isnull=True)),
        ]

    def __str__(self):
        return f"Purchase {self.reference_no} from {self.supplier.name}"


class Sale(BaseModel):

    receipt_no = models.CharField(max_length=100, unique=True)
    cashier = models.ForeignKey(
        AuthorizedUser, on_delete=models.PROTECT, null=True, related_name='sales'
    )
    sale_date = models.DateField()
    status = models.CharField(
        max_length=50,
        choices=[('pending', 'Pending'), ('completed', 'Completed'), ('cancelled', 'Cancelled')],
        default='pending',
    )
    payment_method = models.CharField(
        max_length=50,
        choices=[('cash', 'Cash'), ('credit_card', 'Credit Card'), ('mobile_payment', 'Mobile Payment')],
        default='cash',
    )
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), validators=NONNEGATIVE_MONEY)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), validators=NONNEGATIVE_MONEY)
    change_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), validators=NONNEGATIVE_MONEY)
    voided_by = models.ForeignKey(
        AuthorizedUser, on_delete=models.PROTECT, null=True, blank=True,
        related_name='voided_sales',
    )
    voided_at = models.DateTimeField(blank=True, null=True)
    void_reason = models.TextField(blank=True, null=True)

    cashier_auth = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name='pandora_sales')
    voided_by_auth = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name='pandora_sales_cancelled')

    class Meta:
        indexes = [models.Index(fields=['status', 'sale_date'], name='sale_status_date')]
        constraints = [
            check('sale_receipt_not_empty', ~Q(receipt_no='')),
            check('sale_money_nonnegative', Q(total_amount__gte=0, amount_paid__gte=0, change_amount__gte=0)),
            check('sale_status_valid', Q(status__in=['pending', 'completed', 'cancelled'])),
            check('sale_payment_valid', Q(payment_method__in=['cash', 'credit_card', 'mobile_payment'])),
            check('sale_completed_cashier', ~Q(status='completed') | Q(cashier_auth__isnull=False)),
            check('sale_completed_payment', ~Q(status='completed')
                | Q(payment_method='cash', amount_paid__gte=F('total_amount'),
                    change_amount=F('amount_paid') - F('total_amount'))
                | Q(payment_method__in=['credit_card', 'mobile_payment'],
                    amount_paid=F('total_amount'), change_amount=0)),
            check('sale_cancellation_metadata',
                (Q(status='cancelled', voided_by_auth__isnull=False, voided_at__isnull=False,
                    void_reason__isnull=False) & ~Q(void_reason__regex=r'^\s*$'))
                | (Q(status__in=['pending', 'completed'], voided_by_auth__isnull=True,
                    voided_at__isnull=True) & (Q(void_reason__isnull=True) | Q(void_reason='')))),
        ]

    def __str__(self):
        cashier = self.cashier_auth.get_username() if self.cashier_auth_id else 'Unknown'
        return f"Sale {self.receipt_no} by {cashier}"


class PurchaseItem(BaseModel):

    purchase = models.ForeignKey(Purchase, on_delete=models.PROTECT, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='purchase_items')
    quantity = models.PositiveIntegerField(validators=POSITIVE_QUANTITY)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, validators=NONNEGATIVE_MONEY)

    class Meta:
        constraints = [
            check('purchaseitem_quantity_positive', Q(quantity__gte=1, quantity__lte=MAX_QUANTITY)),
            check('purchaseitem_cost_nonnegative', Q(unit_cost__gte=0)),
        ]

    def __str__(self):
        return f"{self.quantity} x {self.product.name} for Purchase {self.purchase.reference_no}"


class SaleItem(BaseModel):

    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='sale_items')
    quantity = models.PositiveIntegerField(validators=POSITIVE_QUANTITY)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=NONNEGATIVE_MONEY)
    unit_cost_at_sale = models.DecimalField(max_digits=18, decimal_places=6, validators=NONNEGATIVE_MONEY)

    class Meta:
        constraints = [
            check('saleitem_quantity_positive', Q(quantity__gte=1, quantity__lte=MAX_QUANTITY)),
            check('saleitem_money_nonnegative', Q(unit_price__gte=0, unit_cost_at_sale__gte=0)),
        ]

    def __str__(self):
        return f"{self.quantity} x {self.product.name} for Sale {self.sale.receipt_no}"


class StockMovement(BaseModel):

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='stock_movements')
    movement_type = models.CharField(
        max_length=50,
        choices=[('purchase', 'Purchase'), ('sale', 'Sale'), ('adjustment', 'Adjustment')],
    )
    quantity_change = models.IntegerField()
    stock_after = models.PositiveIntegerField(validators=STOCK_RANGE)
    sale_item = models.ForeignKey(
        SaleItem, on_delete=models.PROTECT, null=True, blank=True,
        related_name='stock_movements',
    )
    purchase_item = models.ForeignKey(
        PurchaseItem, on_delete=models.PROTECT, null=True, blank=True,
        related_name='stock_movements',
    )
    performed_by = models.ForeignKey(
        AuthorizedUser, on_delete=models.PROTECT, null=True,
        related_name='stock_movements',
    )
    remarks = models.TextField(blank=True, null=True)

    performed_by_auth = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name='pandora_stock_movements')

    class Meta:
        indexes = [models.Index(fields=['product', 'created_at', 'id'], name='movement_product_time')]
        constraints = [
            check('movement_type_valid', Q(movement_type__in=['purchase', 'sale', 'adjustment'])),
            check('movement_actor_required', Q(performed_by_auth__isnull=False)),
            check('movement_stock_bounds', Q(stock_after__gte=0, stock_after__lte=MAX_QUANTITY)),
            check('movement_quantity_bounds', Q(quantity_change__gte=-MAX_QUANTITY, quantity_change__lte=MAX_QUANTITY)),
            check('movement_source_valid',
                Q(movement_type='sale', sale_item__isnull=False, purchase_item__isnull=True, quantity_change__lt=0)
                | Q(movement_type='purchase', purchase_item__isnull=False, sale_item__isnull=True, quantity_change__gt=0)
                | (Q(movement_type='adjustment', purchase_item__isnull=True, sale_item__isnull=True)
                    & ~Q(quantity_change=0))),
            models.UniqueConstraint(fields=['sale_item'], name='movement_sale_once'),
            models.UniqueConstraint(fields=['purchase_item'], name='movement_purchase_once'),
        ]

    def __str__(self):
        performer = self.performed_by_auth.get_username() if self.performed_by_auth_id else 'Unknown'
        return f"{self.movement_type.capitalize()} of {self.quantity_change} for {self.product.name} by {performer}"

class ExpenseCategory(BaseModel):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name_plural = 'expense categories'
        constraints = [check('expense_category_name_required', ~Q(name__regex=r'^\s*$'))]

    def __str__(self):
        return self.name


class OperatingExpense(BaseModel):
    request_id = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    expense_date = models.DateField()
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name='expenses')
    description = models.TextField()
    amount = models.DecimalField(max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='pandora_expenses_created')
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name='pandora_expenses_voided')
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.TextField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['expense_date'], name='expense_business_date')]
        constraints = [
            check('expense_amount_positive', Q(amount__gt=0)),
            check('expense_description_required', ~Q(description__regex=r'^\s*$')),
            check('expense_void_metadata',
                (Q(voided_by__isnull=True, voided_at__isnull=True)
                    & (Q(void_reason__isnull=True) | Q(void_reason='')))
                | (Q(voided_by__isnull=False, voided_at__isnull=False, void_reason__isnull=False)
                    & ~Q(void_reason__regex=r'^\s*$'))),
        ]

    def __str__(self):
        return f'{self.expense_date}: {self.description}'
