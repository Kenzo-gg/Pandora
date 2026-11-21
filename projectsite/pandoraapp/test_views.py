from django.core import signing
from django.test import Client, TestCase
from django.urls import reverse

from . import services
from .models import Purchase, Sale, StockMovement
from .test_services import Fixtures
from .views import TOKEN_SALT


class TransactionPagesTests(Fixtures, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.client.force_login(self.admin)

    def url(self, name, pk=None):
        return reverse('pandoraapp:' + name, args=[pk] if pk else [])

    def token(self, kind, obj):
        response = self.client.get(self.url(kind + '_detail', obj.pk))
        self.assertEqual(response.status_code, 200)
        return response.context['action_form']['token'].value()

    def test_receipt_sale_and_duplicate_posts(self):
        response = self.client.post(self.url('purchase_create'), {
            'reference': 'UI-P', 'supplier': self.supplier.pk, 'date': '2026-11-15',
            'items-TOTAL_FORMS': 1, 'items-INITIAL_FORMS': 0,
            'items-0-product': self.product.pk, 'items-0-quantity': 10,
            'items-0-unit_cost': '200.00'})
        self.assertEqual(response.status_code, 302)
        purchase = Purchase.objects.get(reference_no='UI-P')
        data = {'token': self.token('purchase', purchase)}
        for _ in range(2):
            self.assertEqual(self.client.post(self.url('purchase_post', purchase.pk), data).status_code, 302)
        response = self.client.post(self.url('sale_create'), {
            'reference': 'UI-S', 'date': '2026-11-15', 'items-TOTAL_FORMS': 1,
            'items-INITIAL_FORMS': 0, 'items-0-product': self.product.pk, 'items-0-quantity': 3})
        self.assertEqual(response.status_code, 302)
        sale = Sale.objects.get(receipt_no='UI-S')
        data = {'token': self.token('sale', sale), 'payment_method': 'cash', 'amount_paid': '1500.00'}
        for _ in range(2):
            self.assertEqual(self.client.post(self.url('sale_post', sale.pk), data).status_code, 302)
        self.product.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(self.product.current_stock, 7)
        self.assertEqual(sale.change_amount, 150)
        self.assertEqual(StockMovement.objects.count(), 2)
        self.assertContains(self.client.get(self.url('sale_detail', sale.pk)), 'Change ₱150.00')

    def test_login_roles_and_ownership(self):
        sale = self.sale()
        cashier = self.role_user('cashier_ui', 'Cashier', ['add_sale', 'change_sale'])
        self.client.force_login(cashier)
        for url in [self.url('purchase_create'), self.url('reorder'), self.url('sale_detail', sale.pk)]:
            self.assertEqual(self.client.get(url).status_code, 403)
        own = services.create_sale_draft(actor=cashier, receipt_no='OWN', sale_date='2026-11-15',
                    lines=[{'product_id': self.product.pk, 'quantity': 1}])
        response = self.client.get(self.url('sale_detail', own.pk))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'unit_cost_at_sale')
        self.client.logout()
        self.assertEqual(self.client.get(self.url('purchase_create')).status_code, 302)

    def test_post_only_and_csrf(self):
        purchase = self.purchase()
        self.assertEqual(self.client.get(self.url('purchase_post', purchase.pk)).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.url('purchase_post', purchase.pk), {}).status_code, 403)

    def test_invalid_and_stale_tokens_do_not_receive(self):
        purchase = self.purchase()
        token = self.token('purchase', purchase)
        services.replace_purchase_lines(actor=self.admin, purchase_id=purchase.pk,
            expected_lines=services.purchase_snapshot(actor=self.admin, purchase_id=purchase.pk),
            lines=[{'product_id': self.product.pk, 'quantity': 2, 'unit_cost': '200.00'}])
        for value in ['invalid', token]:
            response = self.client.post(self.url('purchase_post', purchase.pk), {'token': value})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['action_form'].errors)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_line_validation_and_limits(self):
        for count, quantity in [(0, ''), (1, ''), (1, '-2'), (51, '1')]:
            response = self.client.post(self.url('purchase_create'), {
                'reference': 'BAD', 'supplier': self.supplier.pk, 'date': '2026-11-15',
                'items-TOTAL_FORMS': count, 'items-INITIAL_FORMS': 0,
                'items-0-product': self.product.pk, 'items-0-quantity': quantity,
                'items-0-unit_cost': '200.00'})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(Purchase.objects.count(), 0)

    def test_cancellation_and_reorder(self):
        purchase = self.purchase()
        self.assertEqual(self.client.post(self.url('purchase_cancel', purchase.pk), {'reason': '   '}).status_code, 200)
        self.assertEqual(self.client.post(self.url('purchase_cancel', purchase.pk), {'reason': 'Duplicate order'}).status_code, 302)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, 'cancelled')
        self.assertContains(self.client.get(self.url('reorder')), 'Out of stock')

    def test_catalog_search_and_cashier_cost_privacy(self):
        cashier = self.role_user('catalog_cashier', 'Cashier', ['change_sale'])
        self.client.force_login(cashier)
        response = self.client.get(self.url('products'), {'q': self.product.sku})
        self.assertContains(response, self.product.name)
        self.assertNotIn('cost_price', response.context['page'][0])
        self.assertContains(self.client.get(self.url('products'), {'q': 'missing'}), 'No products match')
        self.product.is_active = False
        self.product.save()
        self.assertContains(self.client.get(self.url('products')), 'No products match')

    def test_cashier_history_is_scoped_and_inventory_cannot_sell(self):
        other = self.sale()
        cashier = self.role_user('history_cashier', 'Cashier', ['change_sale', 'add_sale'])
        own = services.create_sale_draft(actor=cashier, receipt_no='CASHIER-OWN',
            sale_date='2026-11-15', lines=[{'product_id': self.product.pk, 'quantity': 1}])
        self.client.force_login(cashier)
        response = self.client.get(self.url('sale_history'))
        self.assertContains(response, own.receipt_no)
        self.assertNotContains(response, other.receipt_no)
        self.assertEqual(self.client.get(self.url('purchase_history')).status_code, 403)
        inventory = self.role_user('inventory_history', 'Inventory Staff', ['view_product', 'change_purchase'])
        self.client.force_login(inventory)
        self.assertEqual(self.client.get(self.url('products')).status_code, 200)
        self.assertEqual(self.client.get(self.url('purchase_history')).status_code, 200)
        self.assertEqual(self.client.get(self.url('sale_history')).status_code, 403)

    def test_history_filters_and_pagination(self):
        purchase = self.purchase()
        self.receive(purchase)
        self.purchase()
        response = self.client.get(self.url('purchase_history'), {'status': 'completed'})
        self.assertEqual(list(response.context['page']), [purchase])
        response = self.client.get(self.url('purchase_history'), {'q': 'MISSING'})
        self.assertContains(response, 'No transactions match')
        for _ in range(25):
            self.purchase()
        response = self.client.get(self.url('purchase_history'), {'page': 2})
        self.assertEqual(len(response.context['page']), 2)

    def test_history_date_filter_and_bad_dates(self):
        early, late = self.purchase(), self.purchase()
        Purchase.objects.filter(pk=early.pk).update(order_date='2026-10-01')
        Purchase.objects.filter(pk=late.pk).update(order_date='2026-11-15')
        url = self.url('purchase_history')
        response = self.client.get(url, {'start': '2026-11-01', 'end': '2026-11-30'})
        self.assertEqual(list(response.context['page']), [late])
        response = self.client.get(url, {'end': '2026-10-31'})
        self.assertEqual(list(response.context['page']), [early])
        response = self.client.get(url, {'start': 'not-a-date'})
        self.assertEqual(len(response.context['page']), 2)

    def test_sale_form_lists_price_stock_and_search_text(self):
        self.product.refresh_from_db()
        response = self.client.get(self.url('sale_create'))
        self.assertContains(response, 'data-price="%s"' % self.product.selling_price)
        self.assertContains(response, 'data-stock="%s"' % self.product.current_stock)
        self.assertContains(response, 'data-search="%s' % self.product.sku.lower())
        self.assertContains(response, 'Estimated total')

    def test_sales_report_totals_and_periods(self):
        self.receive(self.purchase())
        sale = self.sale(quantity=2)
        self.complete(sale)
        self.sale()  # Pending transactions must never contribute to revenue.
        for period, label in [('daily', '2026-11-12'), ('weekly', '2026-11-09 to 2026-11-15'), ('monthly', '2026-11')]:
            response = self.client.get(self.url('sales_report'), {
                'start': '2026-11-12', 'end': '2026-11-12', 'period': period})
            self.assertEqual(response.status_code, 200)
            report = response.context['report']
            self.assertEqual(report['totals'], {'transactions': 1, 'units': 2, 'revenue': 900})
            self.assertEqual(report['rows'][0]['label'], label)
            self.assertEqual(report['products'], [{'sku': self.product.sku,
                'name': self.product.name, 'units': 2, 'revenue': 900}])
            self.assertContains(response, self.product.name)
        response = self.client.get(self.url('sales_report'), {
            'start': '2026-11-13', 'end': '2026-11-13', 'period': 'daily', 'format': 'pdf'})
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF-'))

    def test_sales_report_validation_and_access(self):
        response = self.client.get(self.url('sales_report'), {'start': '2026-12-01', 'end': '2026-11-01'})
        self.assertTrue(response.context['form'].errors)
        cashier = self.role_user('report_cashier', 'Cashier', ['view_sale', 'change_sale'])
        self.client.force_login(cashier)
        for extra in [{}, {'format': 'pdf'}]:
            self.assertEqual(self.client.get(self.url('sales_report'), extra).status_code, 403)
        inventory = self.role_user('report_inventory', 'Inventory Staff', ['view_sale'])
        self.client.force_login(inventory)
        self.assertEqual(self.client.get(self.url('sales_report')).status_code, 403)
        admin = self.role_user('report_admin', 'Admin', ['view_sale'])
        self.client.force_login(admin)
        self.assertEqual(self.client.get(self.url('sales_report')).status_code, 200)

    def test_product_breakdown_uses_saved_sale_prices(self):
        self.receive(self.purchase())
        self.complete(self.sale(quantity=2))
        self.product.refresh_from_db()
        self.product.selling_price = 500
        self.product.save(update_fields=['selling_price'])
        self.complete(self.sale(quantity=1))
        self.product.selling_price = 999
        self.product.save(update_fields=['selling_price'])
        response = self.client.get(self.url('sales_report'), {
            'start': '2026-11-12', 'end': '2026-11-12', 'period': 'daily'})
        product = response.context['report']['products'][0]
        self.assertEqual(product['units'], 3)
        self.assertEqual(product['revenue'], 1400)
        self.assertEqual(response.context['report']['totals']['revenue'], 1400)

    def test_inventory_report_filters_and_thresholds(self):
        url = self.url('inventory_report')
        response = self.client.get(url)
        self.assertContains(response, 'Out of stock')
        self.assertEqual(response.context['report']['units'], 0)
        self.assertNotIn('cost_price', response.context['report']['rows'][0])
        self.receive(self.purchase(quantity=5))
        response = self.client.get(url, {'status': 'low', 'category': self.category.pk, 'q': self.product.sku})
        self.assertEqual(response.context['report']['units'], 5)
        self.assertEqual(response.context['report']['rows'][0]['stock_status'], 'Low stock')
        self.assertContains(self.client.get(url, {'status': 'out'}), 'No products match')
        self.assertContains(self.client.get(url, {'status': 'available'}), 'No products match')
        self.receive(self.purchase(quantity=1))
        self.assertEqual(self.client.get(url, {'status': 'available'}).context['report']['units'], 6)
        self.product.is_active = False
        self.product.save(update_fields=['is_active'])
        self.assertContains(self.client.get(url), 'No products match')
        self.assertEqual(self.client.get(url, {'active': 'all'}).context['report']['product_count'], 1)

    def test_inventory_report_access_validation_and_pdf(self):
        url = self.url('inventory_report')
        inventory = self.role_user('inventory_report', 'Inventory Staff', ['view_product'])
        self.client.force_login(inventory)
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.get(url, {'format': 'pdf', 'q': 'missing'})
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF-'))
        response = self.client.get(url, {'category': 'invalid', 'format': 'pdf'})
        self.assertTrue(response.context['form'].errors)
        cashier = self.role_user('inventory_cashier', 'Cashier', ['view_product'])
        self.client.force_login(cashier)
        for data in [{}, {'format': 'pdf'}]:
            self.assertEqual(self.client.get(url, data).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
