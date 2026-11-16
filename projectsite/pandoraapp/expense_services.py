"""Immutable expense entry with retry protection and audited voiding."""
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import OperatingExpense
from .services import StockError, _authorize


@transaction.atomic
def record_expense(*, actor, request_id, expense_date, category, description, amount):
    user = _authorize(actor, {'Admin'}, 'add_operatingexpense')
    # Serialize retries from this account, then enforce the global unique request ID.
    get_user_model().objects.select_for_update().get(pk=user.pk)
    request_id = UUID(str(request_id))
    existing = OperatingExpense.objects.filter(request_id=request_id).first()
    values = {'expense_date': expense_date, 'category_id': category.pk,
              'description': description.strip(), 'amount': amount, 'created_by_id': user.pk}
    if existing:
        if any(getattr(existing, key) != value for key, value in values.items()):
            raise StockError('This request was already used with different expense details.')
        return existing
    expense = OperatingExpense(request_id=request_id, **values)
    expense.full_clean()
    expense.save()
    return expense


@transaction.atomic
def void_expense(*, actor, expense_id, reason):
    user = _authorize(actor, {'Admin'}, 'change_operatingexpense')
    if not reason.strip():
        raise StockError('A reason is required.')
    expense = OperatingExpense.objects.select_for_update().get(pk=expense_id)
    if expense.voided_at:
        return expense
    expense.voided_by = user
    expense.voided_at = timezone.now()
    expense.void_reason = reason.strip()
    expense.full_clean()
    expense.save(update_fields=['voided_by', 'voided_at', 'void_reason', 'updated_at'])
    return expense
