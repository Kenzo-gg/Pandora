from django.test import TestCase
from django.urls import reverse

from .models import Category, Product
from .test_services import Fixtures


class ProductFilterTests(Fixtures, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.client.force_login(self.admin)
        self.url = reverse('pandoraapp:products')
        self.mouse_category = Category.objects.create(name='Mice')
        self.mouse = Product.objects.create(category=self.mouse_category, sku='MOUSE-1',
            name='Pulsar Mouse', brand='Pulsar', model='X2', selling_price='2000',
            current_stock=3, reorder_level=5)
        self.other = Product.objects.create(category=self.mouse_category, sku='MOUSE-2',
            name='Other Mouse', brand='Other', model='Y', selling_price='3000',
            current_stock=10, reorder_level=5)

    def skus(self, params):
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        return [row['sku'] for row in response.context['page']]

    def test_combined_filters_and_price_boundaries(self):
        self.assertEqual(self.skus(dict(q='mouse', category=self.mouse_category.pk,
            brand='Pulsar', stock='low', min_price='2000', max_price='2000')), ['MOUSE-1'])
        self.assertEqual(self.skus({'category': self.category.pk}), [self.product.sku])
        self.assertEqual(self.skus({'brand': 'Other'}), ['MOUSE-2'])
        self.assertEqual(self.skus({'min_price': '2000.01'}), ['MOUSE-2'])

    def test_stock_states_and_inactive_products(self):
        self.assertEqual(self.skus({'stock': 'out'}), [self.product.sku])
        self.assertEqual(self.skus({'stock': 'low'}), ['MOUSE-1'])
        self.assertCountEqual(self.skus({'stock': 'available'}), ['MOUSE-1', 'MOUSE-2'])
        self.mouse.is_active = False
        self.mouse.save()
        self.assertEqual(self.skus({'stock': 'low'}), [])
        self.assertNotIn('Pulsar', dict(self.client.get(self.url).context[
            'filter_form'].fields['brand'].choices))

    def test_filter_count_ignores_status_the_view_does_not_apply(self):
        count = lambda params: self.client.get(self.url, params).context['active_filters']
        self.assertEqual(count({'stock': 'low', 'show': 'all'}), 2)
        self.assertEqual(count({'show': 'bogus'}), 0)  # unknown status falls back to active
        self.client.force_login(self.role_user('filter_cashier', 'Cashier', ['view_sale', 'change_sale', 'add_sale', 'view_product']))
        self.assertEqual(count({'show': 'all'}), 0)  # cashiers can't filter by status

    def test_invalid_filters_show_errors_without_crashing(self):
        for params in ({'min_price': '-1'}, {'min_price': 'NaN'}, {'max_price': 'abc'},
                       {'min_price': '3000', 'max_price': '2000'},
                       {'category': 'invalid'}, {'stock': 'invalid'}, {'brand': 'invalid'}):
            with self.subTest(params=params):
                response = self.client.get(self.url, params)
                self.assertTrue(response.context['filter_form'].errors)
                self.assertEqual(list(response.context['page']), [])

    def test_pagination_preserves_filters_and_reset_clears_them(self):
        Product.objects.bulk_create([Product(category=self.mouse_category, sku=f'EXTRA-{i}',
            name=f'Pulsar extra {i:02}', brand='Pulsar', model='X2', selling_price='2000',
            current_stock=3, reorder_level=5) for i in range(26)])
        params = dict(q='Pulsar', brand='Pulsar', category=self.mouse_category.pk,
                      stock='low', min_price='1000', max_price='2500')
        response = self.client.get(self.url, params)
        self.assertEqual(response.context['page'].paginator.count, 27)
        self.assertContains(response, 'stock=low')
        self.assertContains(response, 'min_price=1000')
        self.assertContains(response, 'page=2')
        self.assertContains(response, f'href="{self.url}">Reset</a>')
        self.assertEqual(len(self.skus(dict(params, page=2))), 2)
