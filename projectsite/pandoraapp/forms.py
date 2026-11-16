from decimal import Decimal

from django import forms
from django.forms import formset_factory
from django.utils import timezone

from .models import MAX_QUANTITY, Product, Sale, Supplier


class PurchaseHeaderForm(forms.Form):
    reference = forms.CharField(max_length=100, widget=forms.HiddenInput)
    supplier = forms.ModelChoiceField(queryset=Supplier.objects.filter(is_active=True))
    date = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(attrs={'type': 'date'}))


class SaleHeaderForm(forms.Form):
    reference = forms.CharField(max_length=100, widget=forms.HiddenInput)
    date = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(attrs={'type': 'date'}))


class SaleLineForm(forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.filter(is_active=True))
    quantity = forms.IntegerField(min_value=1, max_value=MAX_QUANTITY)


class PurchaseLineForm(SaleLineForm):
    unit_cost = forms.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0'))


PurchaseLines = formset_factory(PurchaseLineForm, extra=1, min_num=1,
                               validate_min=True, max_num=50, validate_max=True, absolute_max=50)
SaleLines = formset_factory(SaleLineForm, extra=1, min_num=1,
                           validate_min=True, max_num=50, validate_max=True, absolute_max=50)


class ConfirmationForm(forms.Form):
    token = forms.CharField(widget=forms.HiddenInput)


class PaymentForm(ConfirmationForm):
    payment_method = forms.ChoiceField(choices=Sale._meta.get_field('payment_method').choices)
    amount_paid = forms.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0'))


class CancellationForm(forms.Form):
    reason = forms.CharField(max_length=1000, strip=True)
