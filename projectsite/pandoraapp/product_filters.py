from django import forms

from .models import Category, Product


class ProductFilterForm(forms.Form):
    q = forms.CharField(label='Search by name, SKU, brand or category', required=False,
                        max_length=100, widget=forms.TextInput(attrs={'type': 'search'}))
    category = forms.ModelChoiceField(label='Category', required=False,
                                     queryset=Category.objects.none(), empty_label='All categories')
    brand = forms.ChoiceField(label='Brand', required=False)
    stock = forms.ChoiceField(label='Availability', required=False, choices=[
        ('', 'All stock levels'), ('available', 'In stock'),
        ('low', 'Low stock'), ('out', 'Out of stock')])
    min_price = forms.DecimalField(label='Min price (₱)', required=False, min_value=0,
                                   max_digits=10, decimal_places=2)
    max_price = forms.DecimalField(label='Max price (₱)', required=False, min_value=0,
                                   max_digits=10, decimal_places=2)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.filter(
            products__is_active=True).distinct().order_by('name', 'pk')
        brands = Product.objects.filter(is_active=True).exclude(brand='').order_by(
            'brand').values_list('brand', flat=True).distinct()
        self.fields['brand'].choices = [('', 'All brands')] + [(brand, brand) for brand in brands]

    def clean(self):
        data = super().clean()
        lower, upper = data.get('min_price'), data.get('max_price')
        if lower is not None and upper is not None and lower > upper:
            self.add_error('max_price', 'Max price must be at least the min price.')
        return data
