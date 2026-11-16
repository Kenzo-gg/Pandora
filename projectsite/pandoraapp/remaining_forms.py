from decimal import Decimal

from django import forms
from django.utils import timezone

from .models import ExpenseCategory
from .reports import MANILA


class ExpenseForm(forms.Form):
    token = forms.CharField(widget=forms.HiddenInput)
    expense_date = forms.DateField(initial=lambda: timezone.now().astimezone(MANILA).date(),
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}))
    category = forms.ModelChoiceField(queryset=ExpenseCategory.objects.order_by('name'))
    description = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={'rows': 3}))
    amount = forms.DecimalField(min_value=Decimal('0.01'), max_digits=10, decimal_places=2)


class ExpenseCategoryForm(forms.Form):
    name = forms.CharField(max_length=100)
