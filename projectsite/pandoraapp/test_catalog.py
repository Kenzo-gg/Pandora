from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from .models import Category, Product
from .test_services import Fixtures


class CatalogPagesTests(Fixtures, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.client.force_login(self.admin)

    def url(self, name, pk=None):
        return reverse('pandoraapp:' + name, args=[pk] if pk else [])

    def product_data(self, **changes):
        data = {'sku': 'test-ms', 'name': 'Synthetic mouse', 'category': self.category.pk, 'brand': 'Test',
                'model': 'M1', 'preferred_supplier': self.supplier.pk, 'selling_price': '250.00',
                'reorder_level': 3, 'warranty_months': '', 'description': '', 'is_active': 'on'}
        data.update(changes)
        return data

    def test_add_and_edit_product_never_touches_stock_or_cost(self):
        response = self.client.post(self.url('product_create'), self.product_data())
        product = Product.objects.get(sku='TEST-MS')  # SKU is normalised to upper case
        self.assertRedirects(response, self.url('product_edit', product.pk))
        self.assertEqual((product.current_stock, product.cost_price), (0, Decimal('0')))
        self.receive(self.purchase(quantity=4, cost='100.00', product=product))
        self.client.post(self.url('product_edit', product.pk),
                         self.product_data(selling_price='275.00', current_stock=999, cost_price='1'))
        product.refresh_from_db()
        self.assertEqual(product.selling_price, Decimal('275.00'))
        self.assertEqual(product.current_stock, 4)
        self.assertEqual(product.cost_price, Decimal('100.000000'))

    def test_duplicate_sku_is_rejected(self):
        response = self.client.post(self.url('product_create'), self.product_data(sku='test-kb'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['form'].is_valid())

    def test_unused_product_is_deleted(self):
        unused = Product.objects.create(category=self.category, sku='TEST-UNUSED', name='Unused',
                                        brand='T', model='T', selling_price=Decimal('10'))
        response = self.client.post(self.url('product_remove', unused.pk))
        self.assertRedirects(response, self.url('products'))
        self.assertFalse(Product.objects.filter(pk=unused.pk).exists())

    def test_product_with_history_is_deactivated_not_deleted(self):
        self.receive(self.purchase())
        response = self.client.post(self.url('product_remove', self.product.pk))
        self.assertRedirects(response, self.url('product_edit', self.product.pk))
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_active)
        self.assertEqual(self.product.purchase_items.count(), 1)
        listing = self.client.get(self.url('products'))
        self.assertNotContains(listing, self.product.sku)
        listing = self.client.get(self.url('products'), {'show': 'inactive'})
        self.assertContains(listing, self.product.sku)

    def test_categories_add_rename_and_guarded_delete(self):
        self.client.post(self.url('category_create'), {'name': 'Synthetic mice', 'description': ''})
        mice = Category.objects.get(name='Synthetic mice')
        response = self.client.post(self.url('category_create'), {'name': 'synthetic MICE'})
        self.assertFalse(response.context['form'].is_valid())
        self.client.post(self.url('category_delete', self.category.pk))  # still has a product
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())
        self.client.post(self.url('category_delete', mice.pk))
        self.assertFalse(Category.objects.filter(pk=mice.pk).exists())

    def test_roles(self):
        cashier = self.role_user('catalog_cashier', 'Cashier', ['change_sale', 'add_product', 'change_product'])
        self.client.force_login(cashier)
        self.assertEqual(self.client.get(self.url('product_create')).status_code, 403)
        self.assertEqual(self.client.get(self.url('categories')).status_code, 403)
        self.assertNotContains(self.client.get(self.url('products')), 'Add product')
        inventory = self.role_user('catalog_inventory', 'Inventory Staff',
                                   ['view_product', 'change_product', 'view_category'])
        self.client.force_login(inventory)
        self.assertEqual(self.client.get(self.url('product_edit', self.product.pk)).status_code, 200)
        self.assertEqual(self.client.get(self.url('product_create')).status_code, 403)  # no add_product
        unused = Product.objects.create(category=self.category, sku='TEST-ROLE', name='Role test',
                                        brand='T', model='T', selling_price=Decimal('10'))
        self.assertEqual(self.client.post(self.url('product_remove', unused.pk)).status_code, 403)
