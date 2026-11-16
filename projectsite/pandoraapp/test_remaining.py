from datetime import date
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth.models import Group
from django.core import signing
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from .business_reports import performance, profit_loss
from .expense_services import record_expense, void_expense
from .models import ExpenseCategory, OperatingExpense, Product
from .services import StockError
from .test_services import Fixtures, TODAY


class RemainingFeaturesTests(Fixtures, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.client.force_login(self.admin)
        self.expense_category = ExpenseCategory.objects.create(name='Synthetic rent')

    def url(self, name, *args):
        return reverse('pandoraapp:' + name, args=args)

    def test_product_thresholds_zero_sales_and_inactive_sold(self):
        self.receive(self.purchase(quantity=20))
        self.complete(self.sale(quantity=10), paid='4500')
        zero = Product.objects.create(category=self.category, sku='ZERO', name='Zero sales', brand='Test', model='Test', selling_price=1)
        result = performance(actor=self.admin, start=TODAY, end=TODAY)
        rows = {row[0]: row for row in result['rows']}
        self.assertEqual(rows[self.product.sku][2:], [10, 'Fast-selling'])
        self.assertEqual(rows[zero.sku][2:], [0, 'Slow-selling'])
        self.product.is_active = False
        self.product.save(update_fields=['is_active'])
        self.assertEqual(len(performance(actor=self.admin, start=TODAY, end=TODAY)['rows']), 2)

    def test_expense_retry_conflict_and_void_preserve_history(self):
        values = dict(actor=self.admin, request_id=uuid4(), expense_date=TODAY,
            category=self.expense_category, description='Synthetic rent payment', amount=Decimal('100'))
        expense = record_expense(**values)
        self.assertEqual(record_expense(**values).pk, expense.pk)
        with self.assertRaises(StockError):
            record_expense(**{**values, 'amount': Decimal('101')})
        void_expense(actor=self.admin, expense_id=expense.pk, reason='Synthetic correction')
        void_expense(actor=self.admin, expense_id=expense.pk, reason='Retry')
        expense.refresh_from_db()
        self.assertEqual(expense.amount, 100)
        self.assertEqual(expense.void_reason, 'Synthetic correction')
        self.assertEqual(OperatingExpense.objects.count(), 1)

    def test_profit_uses_saved_cost_and_excludes_voided_expenses(self):
        self.receive(self.purchase(cost='200'))
        self.complete(self.sale(quantity=2))
        expense = record_expense(actor=self.admin, request_id=uuid4(), expense_date=TODAY,
            category=self.expense_category, description='Synthetic expense', amount=Decimal('100'))
        result = profit_loss(actor=self.admin, start=TODAY, end=TODAY)
        self.assertEqual(dict(result['rows'])['Operating profit/loss'], '400.00')
        self.assertEqual(dict(result['rows'])['Historical cost of goods sold'], '400.00')
        void_expense(actor=self.admin, expense_id=expense.pk, reason='Test void')
        self.assertEqual(dict(profit_loss(actor=self.admin, start=TODAY, end=TODAY)['rows'])['Operating profit/loss'], '500.00')
        scoped = profit_loss(actor=self.admin, start=TODAY, end=TODAY, category=self.category)
        self.assertNotIn('Operating profit/loss', dict(scoped['rows']))

    def test_expense_page_retry_and_validation(self):
        url = self.url('expense_create')
        response = self.client.get(url)
        token = response.context['form']['token'].value()
        data = {'token': token, 'expense_date': TODAY.isoformat(), 'category': self.expense_category.pk,
                'description': 'Synthetic payment', 'amount': '10.00'}
        for _ in range(2):
            self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(OperatingExpense.objects.count(), 1)
        for invalid in [{'amount': '0'}, {'description': ' '}, {'token': 'tampered'}]:
            response = self.client.post(url, {**data, **invalid})
            self.assertTrue(response.context['form'].errors)
        expense = OperatingExpense.objects.get()
        url = self.url('expense_void', expense.pk)
        self.client.get(url)
        expense.refresh_from_db()
        self.assertIsNone(expense.voided_at)
        self.assertEqual(self.client.post(url, {'reason': 'Correction'}).status_code, 302)

    def test_outputs_and_reports_permissions(self):
        purchase = self.purchase()
        self.assertEqual(self.client.get(self.url('purchase_pdf', purchase.pk)).status_code, 409)
        self.receive(purchase)
        self.assertTrue(self.client.get(self.url('purchase_pdf', purchase.pk)).content.startswith(b'%PDF-'))
        sale = self.sale()
        self.complete(sale)
        self.assertTrue(self.client.get(self.url('sale_pdf', sale.pk)).content.startswith(b'%PDF-'))
        params = {'start': TODAY.isoformat(), 'end': TODAY.isoformat()}
        for name in ['performance_report', 'profit_report', 'movement_report']:
            self.assertEqual(self.client.get(self.url(name), params).status_code, 200)
            self.assertEqual(self.client.get(self.url(name), {**params, 'format': 'pdf'})['Content-Type'], 'application/pdf')
        cashier = self.role_user('remaining_cashier', 'Cashier', ['view_sale', 'change_sale', 'view_product'])
        self.client.force_login(cashier)
        for name in ['performance_report', 'profit_report', 'movement_report', 'expenses', 'expense_create', 'expense_category']:
            self.assertEqual(self.client.get(self.url(name)).status_code, 403)
        self.assertEqual(self.client.get(self.url('sale_pdf', sale.pk)).status_code, 403)
        self.assertEqual(self.client.get(self.url('purchase_pdf', purchase.pk)).status_code, 403)
        inventory = self.role_user('remaining_inventory', 'Inventory Staff', ['view_product', 'view_sale'])
        self.client.force_login(inventory)
        self.assertEqual(self.client.get(self.url('profit_report')).status_code, 403)
        self.assertEqual(self.client.get(self.url('movement_report'), params).status_code, 200)

    def test_form_validation_and_csrf(self):
        response = self.client.get(self.url('performance_report'), {'start': '2026-11-15',
            'end': '2026-11-01', 'fast': 2, 'slow': 3})
        self.assertTrue(response.context['form'].errors)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.url('expense_create'), {}).status_code, 403)

    def test_cashier_dashboard_hides_financial_and_purchase_links(self):
        cashier = self.role_user('dashboard_cashier', 'Cashier', ['view_sale', 'change_sale', 'add_sale', 'view_product'])
        self.client.force_login(cashier)
        response = self.client.get(self.url('home'))
        self.assertContains(response, 'New sale')
        self.assertNotContains(response, 'Basic profit/loss')
        self.assertNotContains(response, 'Purchase history')
        self.assertNotContains(response, 'Inventory report')

    def test_backup_retention_and_failure_logging(self):
        from datetime import datetime, timedelta
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from .backup_tools import run_backup
        import json

        with TemporaryDirectory() as directory:
            for offset in range(9):
                with patch('pandoraapp.backup_tools.datetime') as clock, patch('pandoraapp.backup_tools.snapshot', return_value={}):
                    clock.now.return_value = datetime(2026, 11, 1) + timedelta(days=offset)
                    run_backup(directory)
            paths = list(Path(directory).glob('pandora-*.dpapi'))
            self.assertEqual(len(paths), 7)
            self.assertFalse((Path(directory) / 'pandora-2026-11-01.dpapi').exists())
            with patch('pandoraapp.backup_tools.snapshot', side_effect=RuntimeError('Synthetic failure')):
                with self.assertRaises(RuntimeError):
                    run_backup(directory)
            self.assertEqual(len(list(Path(directory).glob('pandora-*.dpapi'))), 7)
            log = (Path(directory) / 'backup-log.jsonl').read_text().splitlines()
            self.assertEqual(json.loads(log[-1])['status'], 'failed')


class BackupRecoveryTests(Fixtures, TransactionTestCase):
    def test_populated_backup_restore_matches_all_tables(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from .backup_tools import protect, restore_verify, snapshot
        import pickle

        self.make_fixtures()
        self.receive(self.purchase())
        self.complete(self.sale())
        category = ExpenseCategory.objects.create(name='Recovery test expense')
        record_expense(actor=self.admin, request_id=uuid4(), expense_date=TODAY,
            category=category, description='Synthetic recovery expense', amount=Decimal('20'))
        data = snapshot()
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / 'synthetic.dpapi'
            path.write_bytes(protect(pickle.dumps(data, protocol=4)))
            result = restore_verify(path)
        self.assertTrue(result['all_tables_match'])
        for name in ['pandoraapp_sale', 'pandoraapp_purchase', 'pandoraapp_operatingexpense', 'pandoraapp_stockmovement', 'auth_user']:
            self.assertGreater(result['tables'][name]['rows'], 0)
