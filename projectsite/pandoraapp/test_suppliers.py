from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from .models import Purchase, Supplier
from .test_services import Fixtures


class SupplierPagesTests(Fixtures, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.client.force_login(self.admin)

    def url(self, name, pk=None):
        return reverse('pandoraapp:' + name, args=[pk] if pk else [])

    def test_list_search_and_status_filter(self):
        Supplier.objects.create(name='Old Parts Co', contact_person='Synthetic', contact_number='TEST',
                                is_active=False)
        response = self.client.get(self.url('suppliers'))
        self.assertContains(response, 'Synthetic supplier')
        self.assertContains(response, 'Old Parts Co')
        response = self.client.get(self.url('suppliers'), {'status': 'inactive'})
        self.assertEqual([s.name for s in response.context['page']], ['Old Parts Co'])
        response = self.client.get(self.url('suppliers'), {'q': 'MISSING'})
        self.assertContains(response, 'No suppliers match')

    def test_detail_shows_history_summary_and_filters(self):
        done = self.purchase(quantity=2, cost='100.00')
        self.receive(done)
        pending = self.purchase()
        Purchase.objects.filter(pk=pending.pk).update(order_date='2026-10-01')
        response = self.client.get(self.url('supplier_detail', self.supplier.pk))
        self.assertEqual(response.context['summary']['count'], 1)
        self.assertEqual(response.context['summary']['total'], Decimal('200.00'))
        self.assertEqual(response.context['summary']['pending'], 1)
        self.assertContains(response, done.reference_no)
        self.assertContains(response, self.product.name)  # preferred-supplier products
        response = self.client.get(self.url('supplier_detail', self.supplier.pk), {'status': 'pending'})
        self.assertEqual(list(response.context['page']), [pending])
        response = self.client.get(self.url('supplier_detail', self.supplier.pk), {'end': '2026-10-31'})
        self.assertEqual(list(response.context['page']), [pending])

    def test_create_edit_and_deactivate(self):
        response = self.client.post(self.url('supplier_create'), {
            'name': 'New Synthetic Supplier', 'contact_person': 'Test', 'contact_number': 'TEST',
            'email': '', 'address': '', 'is_active': 'on'})
        supplier = Supplier.objects.get(name='New Synthetic Supplier')
        self.assertRedirects(response, self.url('supplier_detail', supplier.pk))
        self.client.post(self.url('supplier_edit', supplier.pk), {
            'name': supplier.name, 'contact_person': 'Changed', 'contact_number': 'TEST'})
        supplier.refresh_from_db()
        self.assertEqual(supplier.contact_person, 'Changed')
        self.assertFalse(supplier.is_active)  # unchecked box deactivates, history stays

    def test_purchase_history_supplier_filter_and_prefill(self):
        other = Supplier.objects.create(name='Other Synthetic', contact_person='T', contact_number='T')
        mine = self.purchase()
        response = self.client.get(self.url('purchase_history'), {'supplier': other.pk})
        self.assertEqual(list(response.context['page']), [])
        response = self.client.get(self.url('purchase_history'), {'supplier': self.supplier.pk})
        self.assertEqual(list(response.context['page']), [mine])
        response = self.client.get(self.url('purchase_create'), {'supplier': self.supplier.pk})
        self.assertEqual(response.context['header']['supplier'].value(), self.supplier.pk)

    def test_role_access(self):
        inventory = self.role_user('supplier_inventory', 'Inventory Staff', ['view_supplier'])
        self.client.force_login(inventory)
        self.assertEqual(self.client.get(self.url('suppliers')).status_code, 200)
        self.assertEqual(self.client.get(self.url('supplier_detail', self.supplier.pk)).status_code, 200)
        self.assertEqual(self.client.get(self.url('supplier_create')).status_code, 403)
        cashier = self.role_user('supplier_cashier', 'Cashier', ['view_supplier', 'add_sale'])
        self.client.force_login(cashier)
        self.assertEqual(self.client.get(self.url('suppliers')).status_code, 403)
        self.assertEqual(self.client.get(self.url('supplier_detail', self.supplier.pk)).status_code, 403)
