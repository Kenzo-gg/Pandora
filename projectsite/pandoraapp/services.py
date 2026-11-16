"""Stock services for Pandora. Views/forms must call these instead of editing stock.

Money inputs: Decimal or decimal strings, never float.
Lines: purchase {product_id, quantity, unit_cost}; sale {product_id, quantity}.
Use a stable reference/receipt number for retries. All writes use the default DB.
"""
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from functools import wraps
import json
import re
import time

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import OperationalError, connection, transaction
from django.utils import timezone

from .models import MAX_QUANTITY, Product, Purchase, PurchaseItem, Sale, SaleItem, StockMovement, Supplier

ZERO = Decimal('0.00')
MONEY_MAX = Decimal('99999999.99')
COST_MAX = Decimal('999999999999.999999')
PURCHASE_ROLES = {'Admin', 'Inventory Staff'}
SALE_ROLES = {'Admin', 'Cashier'}


class StockError(ValidationError):
    """A friendly error that a form can show to the user."""


def _atomic_retry(function):
    """Retry a complete standalone transaction, never a failed inner savepoint."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        nested = connection.in_atomic_block
        attempts = 1 if nested else 3
        for attempt in range(attempts):
            try:
                with transaction.atomic():
                    return function(*args, **kwargs)
            except OperationalError as exc:
                if not exc.args or exc.args[0] not in (1205, 1213) or nested or attempt == attempts - 1:
                    raise
                time.sleep(0.05 * (attempt + 1))
    return wrapped


def _authorize(actor, roles, permission):
    if not getattr(actor, 'is_authenticated', False) or not getattr(actor, 'pk', None):
        raise PermissionDenied('Please sign in first.')
    try:
        user = get_user_model().objects.get(pk=actor.pk)
    except get_user_model().DoesNotExist:
        raise PermissionDenied('This account is unavailable.') from None
    if not user.is_active:
        raise PermissionDenied('This account is inactive.')
    if not user.is_superuser:
        groups = set(user.groups.values_list('name', flat=True))
        if not groups.intersection(roles) or not user.has_perm('pandoraapp.' + permission):
            raise PermissionDenied('Your account cannot perform this action.')
    return user


def _sale_owner(user, sale):
    if not user.is_superuser and not user.groups.filter(name='Admin').exists():
        if sale.cashier_auth_id != user.pk:
            raise PermissionDenied('You can only work on your own sales.')


def _integer(value, label='Quantity'):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_QUANTITY:
        raise StockError(f'{label} must be a whole number from 1 to {MAX_QUANTITY}.')
    return value


def _money(value, label='Amount'):
    if isinstance(value, (float, bool)):
        raise StockError(f'{label} must be a Decimal or decimal string, not a float.')
    try:
        number = Decimal(value)
        if not number.is_finite() or not ZERO <= number <= MONEY_MAX:
            raise ValueError
        rounded = number.quantize(Decimal('0.01'))
        if rounded != number:
            raise ValueError
        return rounded
    except (InvalidOperation, ValueError, TypeError):
        raise StockError(f'{label} must be nonnegative, within the money limit, with at most 2 decimal places.') from None


def _reference(value):
    if not isinstance(value, str):
        raise StockError('A reference/receipt number is required.')
    value = value.strip().upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9_-]{0,99}', value):
        raise StockError('Use 1–100 letters, numbers, underscores or hyphens for the reference.')
    return value


def _day(value):
    try:
        if isinstance(value, datetime):
            raise ValueError
        return value if isinstance(value, date) else date.fromisoformat(value)
    except (ValueError, TypeError):
        raise StockError('Enter a valid business date as YYYY-MM-DD.') from None


def _reason(value):
    if not isinstance(value, str) or not value.strip():
        raise StockError('A cancellation reason is required.')
    return value.strip()


def _lines_input(lines, purchase):
    if not isinstance(lines, (list, tuple)) or not lines:
        raise StockError('Add at least one item.')
    result = []
    keys = {'product_id', 'quantity', 'unit_cost'} if purchase else {'product_id', 'quantity'}
    for line in lines:
        if not isinstance(line, dict) or set(line) != keys:
            raise StockError('Each item must contain only the documented fields.')
        row = dict(product_id=_integer(line['product_id'], 'Product ID'), quantity=_integer(line['quantity']))
        if purchase:
            row['unit_cost'] = _money(line['unit_cost'], 'Unit cost')
        result.append(row)
    return result


def _get(model, pk, locked=False):
    pk = _integer(pk, 'Record ID')
    query = model.objects.select_for_update() if locked else model.objects
    try:
        return query.get(pk=pk)
    except model.DoesNotExist:
        raise StockError(f'{model.__name__} was not found.') from None


def _products(lines):
    ids = sorted({line['product_id'] if isinstance(line, dict) else line.product_id for line in lines})
    products = {p.pk: p for p in Product.objects.select_for_update().filter(pk__in=ids).order_by('pk')}
    if len(products) != len(ids) or any(not p.is_active for p in products.values()):
        raise StockError('All selected products must exist and be active.')
    return products


def _saved_lines(header):
    lines = list(header.items.order_by('pk'))
    if not lines:
        raise StockError('Add at least one item before completing the transaction.')
    price = 'unit_cost' if isinstance(header, Purchase) else 'unit_price'
    for line in lines:
        _integer(line.quantity)
        _money(getattr(line, price), 'Item price/cost')
    return lines


def _snapshot(lines, purchase):
    field = 'unit_cost' if purchase else 'unit_price'
    return [dict(line_id=line.pk, product_id=line.product_id, quantity=line.quantity,
                 **{field: str(getattr(line, field))}) for line in lines]


def _expected(lines, expected, purchase):
    field = 'unit_cost' if purchase else 'unit_price'
    if not isinstance(expected, (list, tuple)):
        raise StockError('Reload the transaction before submitting it.')
    normalized = []
    for row in expected:
        if not isinstance(row, dict) or set(row) != {'line_id', 'product_id', 'quantity', field}:
            raise StockError('The item snapshot is invalid. Reload the transaction.')
        normalized.append(dict(line_id=_integer(row['line_id'], 'Line ID'),
            product_id=_integer(row['product_id'], 'Product ID'), quantity=_integer(row['quantity']),
            **{field: str(_money(row[field]))}))
    if _snapshot(lines, purchase) != normalized:
        raise StockError('The items changed. Reload and review the transaction.')


def _total(lines, field):
    with localcontext() as context:
        context.prec = 38
        total = sum((line.quantity * getattr(line, field) for line in lines), ZERO)
    return _money(total, 'Transaction total')


def _no_movements(header):
    field = 'purchase_item__purchase' if isinstance(header, Purchase) else 'sale_item__sale'
    if StockMovement.objects.filter(**{field: header}).exists():
        raise StockError('This pending transaction already has stock history; it needs review.')


def _pending(header):
    if header.status != 'pending':
        raise StockError('Only pending transactions can be edited or cancelled.')
    _no_movements(header)


def _supplier(pk):
    supplier = _get(Supplier, pk, locked=True)
    if not supplier.is_active:
        raise StockError('The supplier is inactive.')
    return supplier


def _write_lines(header, data, products, old_lines=()):
    """Only pending-line editing calls this; posted lines are never deleted."""
    purchase = isinstance(header, Purchase)
    # Retain the agreed sale price when the same product remains on that line.
    old_prices = {i: (line.product_id, line.unit_price) for i, line in enumerate(old_lines)} if not purchase else {}
    header.items.all().delete()
    rows = []
    for index, row in enumerate(data):
        if purchase:
            rows.append(PurchaseItem.objects.create(purchase=header, **row))
        else:
            previous = old_prices.get(index)
            price = previous[1] if previous and previous[0] == row['product_id'] else products[row['product_id']].selling_price
            rows.append(SaleItem.objects.create(sale=header, **row, unit_price=_money(price),
                unit_cost_at_sale=Decimal('0.000000')))
    field = 'total_cost' if purchase else 'total_amount'
    setattr(header, field, _total(rows, 'unit_cost' if purchase else 'unit_price'))
    header.save(update_fields=[field, 'updated_at'])


@_atomic_retry
def create_purchase_draft(*, actor, reference_no, supplier_id, order_date, lines):
    user = _authorize(actor, PURCHASE_ROLES, 'add_purchase')
    reference, day = _reference(reference_no), _day(order_date)
    data = _lines_input(lines, True)
    supplier_id = _integer(supplier_id, 'Supplier ID')
    # A read checks existence before FK insertion; the row is locked after the header.
    _get(Supplier, supplier_id)
    header, created = Purchase.objects.get_or_create(reference_no=reference,
        defaults=dict(supplier_id=supplier_id, order_date=day, created_by_auth=user))
    header = _get(Purchase, header.pk, locked=True)
    if not created:
        saved = list(header.items.order_by('pk').values('product_id', 'quantity', 'unit_cost'))
        if (header.created_by_auth_id, header.supplier_id, header.order_date, saved) != (user.pk, supplier_id, day, data):
            raise StockError('This purchase reference is already used for different details.')
        return header
    _supplier(supplier_id)
    products = _products(data)
    _write_lines(header, data, products)
    return header


@_atomic_retry
def create_sale_draft(*, actor, receipt_no, sale_date, lines):
    user = _authorize(actor, SALE_ROLES, 'add_sale')
    reference, day = _reference(receipt_no), _day(sale_date)
    data = _lines_input(lines, False)
    header, created = Sale.objects.get_or_create(receipt_no=reference,
        defaults=dict(sale_date=day, cashier_auth=user))
    header = _get(Sale, header.pk, locked=True)
    _sale_owner(user, header)
    if not created:
        saved = list(header.items.order_by('pk').values('product_id', 'quantity'))
        if (header.cashier_auth_id, header.sale_date, saved) != (user.pk, day, data):
            raise StockError('This receipt number is already used for different details.')
        return header
    products = _products(data)
    _write_lines(header, data, products)
    return header


@_atomic_retry
def purchase_snapshot(*, actor, purchase_id):
    _authorize(actor, PURCHASE_ROLES, 'change_purchase')
    header = _get(Purchase, purchase_id, locked=True)
    return _snapshot(list(header.items.order_by('pk')), True)


@_atomic_retry
def sale_snapshot(*, actor, sale_id):
    user = _authorize(actor, SALE_ROLES, 'change_sale')
    header = _get(Sale, sale_id, locked=True)
    _sale_owner(user, header)
    return _snapshot(list(header.items.order_by('pk')), False)


@_atomic_retry
def replace_purchase_lines(*, actor, purchase_id, lines, expected_lines):
    _authorize(actor, PURCHASE_ROLES, 'change_purchase')
    header = _get(Purchase, purchase_id, locked=True)
    _pending(header)
    old = list(header.items.order_by('pk'))
    _expected(old, expected_lines, True)
    data = _lines_input(lines, True)
    _write_lines(header, data, _products(data))
    return header


@_atomic_retry
def replace_sale_lines(*, actor, sale_id, lines, expected_lines):
    user = _authorize(actor, SALE_ROLES, 'change_sale')
    header = _get(Sale, sale_id, locked=True)
    _sale_owner(user, header)
    _pending(header)
    old = list(header.items.order_by('pk'))
    _expected(old, expected_lines, False)
    data = _lines_input(lines, False)
    _write_lines(header, data, _products(data), old)
    return header


@_atomic_retry
def receive_purchase(*, actor, purchase_id, expected_lines):
    user = _authorize(actor, PURCHASE_ROLES, 'change_purchase')
    header = _get(Purchase, purchase_id, locked=True)
    lines = _saved_lines(header)
    _expected(lines, expected_lines, True)
    if header.status == 'completed':
        return header  # Same saved payload: never receive stock twice.
    _pending(header)
    _supplier(header.supplier_id)
    products = _products(lines)
    total = _total(lines, 'unit_cost')
    incoming = defaultdict(int)
    values = defaultdict(lambda: ZERO)
    with localcontext() as context:
        context.prec = 38
        for line in lines:
            incoming[line.product_id] += line.quantity
            values[line.product_id] += line.quantity * line.unit_cost
        for pk, product in products.items():
            quantity = product.current_stock + incoming[pk]
            if quantity > MAX_QUANTITY:
                raise StockError('Receiving these items would exceed the stock limit.')
            average = ((Decimal(product.current_stock) * product.cost_price + values[pk])
                       / Decimal(quantity)).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)
            if not average.is_finite() or not 0 <= average <= COST_MAX:
                raise StockError('The average cost exceeds its field limit.')
            product.cost_price = average
    balances = {pk: p.current_stock for pk, p in products.items()}
    for line in lines:
        balances[line.product_id] += line.quantity
        StockMovement.objects.create(product_id=line.product_id, movement_type='purchase',
            quantity_change=line.quantity, stock_after=balances[line.product_id],
            purchase_item=line, performed_by_auth=user)
    for pk, product in products.items():
        product.current_stock = balances[pk]
        product.save(update_fields=['current_stock', 'cost_price', 'updated_at'])
    header.total_cost = total
    header.received_by_auth = user
    header.received_at = timezone.now()
    header.status = 'completed'
    header.save(update_fields=['total_cost', 'received_by_auth', 'received_at', 'status', 'updated_at'])
    return header


@_atomic_retry
def complete_sale(*, actor, sale_id, expected_lines, payment_method, amount_paid):
    user = _authorize(actor, SALE_ROLES, 'change_sale')
    header = _get(Sale, sale_id, locked=True)
    _sale_owner(user, header)
    lines = _saved_lines(header)
    _expected(lines, expected_lines, False)
    paid = _money(amount_paid, 'Amount paid')
    if payment_method not in ('cash', 'credit_card', 'mobile_payment'):
        raise StockError('Choose cash, credit_card or mobile_payment.')
    if header.status == 'completed':
        if (header.payment_method, header.amount_paid) != (payment_method, paid):
            raise StockError('This sale was already completed with different payment details.')
        return header
    _pending(header)
    products = _products(lines)
    total = _total(lines, 'unit_price')
    if payment_method == 'cash':
        if paid < total:
            raise StockError('The payment is less than the total.')
        change = paid - total
    else:
        if paid != total:
            raise StockError('Card/mobile payment must exactly match the total.')
        change = ZERO
    needed = defaultdict(int)
    for line in lines:
        needed[line.product_id] += line.quantity
    for pk, quantity in needed.items():
        if products[pk].current_stock < quantity:
            raise StockError(f'Not enough stock for {products[pk].sku}.')
    balances = {pk: p.current_stock for pk, p in products.items()}
    for line in lines:
        line.unit_cost_at_sale = products[line.product_id].cost_price
        line.save(update_fields=['unit_cost_at_sale', 'updated_at'])
        balances[line.product_id] -= line.quantity
        StockMovement.objects.create(product_id=line.product_id, movement_type='sale',
            quantity_change=-line.quantity, stock_after=balances[line.product_id],
            sale_item=line, performed_by_auth=user)
    for pk, product in products.items():
        product.current_stock = balances[pk]
        product.save(update_fields=['current_stock', 'updated_at'])
    header.total_amount, header.amount_paid, header.change_amount = total, paid, change
    header.payment_method, header.status = payment_method, 'completed'
    # Record the actual signed-in operator on the first successful completion.
    header.cashier_auth = user
    header.save(update_fields=['total_amount', 'amount_paid', 'change_amount',
        'payment_method', 'status', 'cashier_auth', 'updated_at'])
    return header


@_atomic_retry
def cancel_sale(*, actor, sale_id, reason):
    user = _authorize(actor, SALE_ROLES, 'change_sale')
    header = _get(Sale, sale_id, locked=True)
    _sale_owner(user, header)
    reason = _reason(reason)
    if header.status == 'cancelled':
        if (header.voided_by_auth_id, header.void_reason) != (user.pk, reason):
            raise StockError('This sale already has different cancellation details.')
        return header
    _pending(header)
    header.status, header.void_reason = 'cancelled', reason
    header.voided_by_auth, header.voided_at = user, timezone.now()
    header.save(update_fields=['status', 'void_reason', 'voided_by_auth', 'voided_at', 'updated_at'])
    return header


@_atomic_retry
def cancel_purchase(*, actor, purchase_id, reason):
    user = _authorize(actor, PURCHASE_ROLES, 'change_purchase')
    header = _get(Purchase, purchase_id, locked=True)
    reason = _reason(reason)
    if header.status == 'cancelled':
        try:
            metadata = json.loads(header.remarks or '{}')
        except (ValueError, TypeError):
            metadata = {}
        if not isinstance(metadata, dict) or (metadata.get('cancelled_by_auth_id'), metadata.get('reason')) != (user.pk, reason):
            raise StockError('This purchase already has different cancellation details.')
        return header
    _pending(header)
    header.remarks = json.dumps(dict(previous_remarks=header.remarks,
        cancelled_by_auth_id=user.pk, cancelled_at=timezone.now().isoformat(), reason=reason))
    header.status = 'cancelled'
    header.save(update_fields=['remarks', 'status', 'updated_at'])
    return header

