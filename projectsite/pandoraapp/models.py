from django.db import models


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

    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='products')
    sku = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    brand = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    current_stock = models.PositiveIntegerField()
    reorder_level = models.PositiveIntegerField()
    warranty_months = models.PositiveIntegerField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

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
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='purchases')
    created_by = models.ForeignKey(
        AuthorizedUser, on_delete=models.SET_NULL, null=True, related_name='purchases'
    )
    order_date = models.DateField()
    status = models.CharField(
        max_length=50,
        choices=[('pending', 'Pending'), ('completed', 'Completed'), ('cancelled', 'Cancelled')],
        default='pending',
    )
    received_by = models.ForeignKey(
        AuthorizedUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='received_purchases',
    )
    received_at = models.DateTimeField(blank=True, null=True)
    total_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    remarks = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Purchase {self.reference_no} from {self.supplier.name}"


class Sale(BaseModel):

    receipt_no = models.CharField(max_length=100, unique=True)
    cashier = models.ForeignKey(
        AuthorizedUser, on_delete=models.SET_NULL, null=True, related_name='sales'
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
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    change_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    voided_by = models.ForeignKey(
        AuthorizedUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='voided_sales',
    )
    voided_at = models.DateTimeField(blank=True, null=True)
    void_reason = models.TextField(blank=True, null=True)

    def __str__(self):
        cashier = self.cashier.username if self.cashier else 'Unknown'
        return f"Sale {self.receipt_no} by {cashier}"


class PurchaseItem(BaseModel):

    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='purchase_items')
    quantity = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.quantity} x {self.product.name} for Purchase {self.purchase.reference_no}"


class SaleItem(BaseModel):

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='sale_items')
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    unit_cost_at_sale = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.quantity} x {self.product.name} for Sale {self.sale.receipt_no}"


class StockMovement(BaseModel):

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_movements')
    movement_type = models.CharField(
        max_length=50,
        choices=[('purchase', 'Purchase'), ('sale', 'Sale'), ('adjustment', 'Adjustment')],
    )
    quantity_change = models.IntegerField()
    stock_after = models.PositiveIntegerField()
    sale_item = models.ForeignKey(
        SaleItem, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stock_movements',
    )
    purchase_item = models.ForeignKey(
        PurchaseItem, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stock_movements',
    )
    performed_by = models.ForeignKey(
        AuthorizedUser, on_delete=models.SET_NULL, null=True,
        related_name='stock_movements',
    )
    remarks = models.TextField(blank=True, null=True)

    def __str__(self):
        performer = self.performed_by.username if self.performed_by else 'Unknown'
        return f"{self.movement_type.capitalize()} of {self.quantity_change} for {self.product.name} by {performer}"