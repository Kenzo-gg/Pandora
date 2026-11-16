"""Database tests: run only through Django's separate test database."""
from datetime import date
from decimal import Decimal
from importlib import import_module
from django.apps import apps
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import connection, IntegrityError, DataError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, RequestFactory
from django.utils import timezone
from .models import (Category, Supplier, Product, Purchase, PurchaseItem, Sale,
    SaleItem, StockMovement, ExpenseCategory, OperatingExpense, AuthorizedUser)


class DatabaseRulesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Explicit synthetic fixtures, never legacy account mappings.
        cls.actor = get_user_model().objects.create_user(username='t04_test_operator', password=None)
        cls.category = Category.objects.create(name='Test category')
        cls.supplier = Supplier.objects.create(name='Test supplier', contact_person='Test', contact_number='Test')
        cls.product = Product.objects.create(category=cls.category, preferred_supplier=cls.supplier,
            sku='TEST-001', name='Test product', brand='Test', model='Test', selling_price=Decimal('10.00'))
        cls.purchase = Purchase.objects.create(reference_no='TEST-P001', supplier=cls.supplier,
            created_by_auth=cls.actor, order_date=date(2026,11,11))
        cls.sale = Sale.objects.create(receipt_no='TEST-S001', cashier_auth=cls.actor, sale_date=date(2026,11,11))
        cls.pi = PurchaseItem.objects.create(purchase=cls.purchase, product=cls.product, quantity=2, unit_cost=Decimal('3.50'))
        cls.si = SaleItem.objects.create(sale=cls.sale, product=cls.product, quantity=1,
            unit_price=Decimal('10.00'), unit_cost_at_sale=Decimal('3.500000'))
        cls.ec = ExpenseCategory.objects.create(name='Test expense')
        cls.expense = OperatingExpense.objects.create(expense_date=date(2026,11,11), category=cls.ec,
            description='Test expense entry', amount=Decimal('20'), created_by=cls.actor)

    def rejects(self, model, pk, **values):
        with self.assertRaises((IntegrityError, DataError)):
            with transaction.atomic():
                model.objects.filter(pk=pk).update(**values)

    def test_negative_product_money(self):
        for field in ('cost_price','selling_price'):
            with self.subTest(field=field): self.rejects(Product,self.product.pk,**{field:Decimal('-0.01')})

    def test_stock_bounds(self):
        for field in ('current_stock','reorder_level'):
            for value in (-1,2147483648):
                with self.subTest(field=field,value=value): self.rejects(Product,self.product.pk,**{field:value})

    def test_zero_and_overflow_quantities(self):
        for model,obj in ((PurchaseItem,self.pi),(SaleItem,self.si)):
            for value in (0,2147483648):
                with self.subTest(model=model.__name__,value=value): self.rejects(model,obj.pk,quantity=value)

    def test_negative_line_money(self):
        for model,obj,field in ((PurchaseItem,self.pi,'unit_cost'),(SaleItem,self.si,'unit_price'),(SaleItem,self.si,'unit_cost_at_sale')):
            with self.subTest(field=field): self.rejects(model,obj.pk,**{field:Decimal('-0.01')})

    def test_negative_header_money(self):
        self.rejects(Purchase,self.purchase.pk,total_cost=-1)
        for field in ('total_amount','amount_paid','change_amount'):
            with self.subTest(field=field): self.rejects(Sale,self.sale.pk,**{field:-1})

    def test_status_and_payment_enums(self):
        self.rejects(Sale,self.sale.pk,status='wrong')
        self.rejects(Purchase,self.purchase.pk,status='wrong')
        self.rejects(Sale,self.sale.pk,payment_method='wrong')

    def test_receipt_metadata(self):
        self.rejects(Purchase,self.purchase.pk,status='completed')
        self.rejects(Purchase,self.purchase.pk,received_at=timezone.now())
        self.rejects(Purchase,self.purchase.pk,created_by_auth=None)
        Purchase.objects.filter(pk=self.purchase.pk).update(status='completed',received_by_auth=self.actor,received_at=timezone.now())

    def test_completed_cashier_and_payment(self):
        self.rejects(Sale,self.sale.pk,status='completed',cashier_auth=None)
        self.rejects(Sale,self.sale.pk,status='completed',total_amount=10,amount_paid=9)
        self.rejects(Sale,self.sale.pk,status='completed',total_amount=10,amount_paid=20,change_amount=0)
        self.rejects(Sale,self.sale.pk,status='completed',payment_method='credit_card',total_amount=10,amount_paid=20,change_amount=10)
        Sale.objects.filter(pk=self.sale.pk).update(status='completed',total_amount=10,amount_paid=20,change_amount=10)

    def test_non_cash_exact_payment(self):
        for method in ('credit_card','mobile_payment'):
            Sale.objects.filter(pk=self.sale.pk).update(status='completed',payment_method=method,total_amount=10,amount_paid=10,change_amount=0)

    def test_cancellation_metadata(self):
        self.rejects(Sale,self.sale.pk,status='cancelled')
        self.rejects(Sale,self.sale.pk,voided_at=timezone.now())
        for reason in ('', '   ', '\t', None):
            with self.subTest(reason=repr(reason)):
                self.rejects(Sale,self.sale.pk,status='cancelled',voided_by_auth=self.actor,voided_at=timezone.now(),void_reason=reason)
        Sale.objects.filter(pk=self.sale.pk).update(status='cancelled',voided_by_auth=self.actor,voided_at=timezone.now(),void_reason='Test cancellation')

    def movement(self, **kwargs):
        data=dict(product=self.product,performed_by_auth=self.actor,movement_type='sale',sale_item=self.si,
                  quantity_change=-1,stock_after=0)
        data.update(kwargs)
        return StockMovement.objects.create(**data)

    def test_bad_movement_shapes(self):
        cases=[dict(movement_type='wrong'),dict(quantity_change=1),dict(quantity_change=0),
            dict(sale_item=None),dict(purchase_item=self.pi),dict(performed_by_auth=None),
            dict(stock_after=2147483648),dict(stock_after=-1),
            dict(movement_type='adjustment'),dict(movement_type='purchase',sale_item=None,purchase_item=self.pi,quantity_change=-2)]
        for values in cases:
            with self.subTest(values=str(values)):
                with self.assertRaises((IntegrityError, DataError)):
                    with transaction.atomic(): self.movement(**values)

    def test_sale_movement_once(self):
        self.movement()
        with self.assertRaises((IntegrityError, DataError)):
            with transaction.atomic(): self.movement()

    def test_purchase_movement_once(self):
        self.movement(movement_type='purchase',sale_item=None,purchase_item=self.pi,quantity_change=2,stock_after=2)
        with self.assertRaises((IntegrityError, DataError)):
            with transaction.atomic(): self.movement(movement_type='purchase',sale_item=None,purchase_item=self.pi,quantity_change=2,stock_after=2)

    def test_nullable_sources_allow_multiple_openings(self):
        for _ in range(2): self.movement(movement_type='adjustment',sale_item=None,quantity_change=1,stock_after=1)
        self.assertEqual(StockMovement.objects.count(),2)

    def test_history_references_protected(self):
        for obj in (self.category,self.supplier,self.product,self.purchase,self.sale,self.actor,self.ec):
            with self.subTest(model=type(obj).__name__):
                with self.assertRaises(ProtectedError): obj.delete()
        self.movement()
        with self.assertRaises(ProtectedError): self.si.delete()

    def test_cost_precision_and_zero_defaults(self):
        self.assertEqual(self.product.current_stock,0)
        self.assertEqual(self.product.cost_price,Decimal('0'))
        Product.objects.filter(pk=self.product.pk).update(cost_price=Decimal('2.666667'))
        SaleItem.objects.filter(pk=self.si.pk).update(unit_cost_at_sale=Decimal('2.666667'))
        self.product.refresh_from_db(); self.si.refresh_from_db()
        self.assertEqual(self.product.cost_price,Decimal('2.666667'))
        self.assertEqual(self.si.unit_cost_at_sale,Decimal('2.666667'))

    def test_expense_validation(self):
        self.rejects(OperatingExpense,self.expense.pk,amount=0)
        self.rejects(OperatingExpense,self.expense.pk,amount=-1)
        self.rejects(OperatingExpense,self.expense.pk,description='   ')
        self.rejects(OperatingExpense,self.expense.pk,voided_at=timezone.now())
        self.rejects(OperatingExpense,self.expense.pk,voided_by=self.actor,voided_at=timezone.now(),void_reason=None)
        self.rejects(OperatingExpense,self.expense.pk,voided_by=self.actor,voided_at=timezone.now(),void_reason='  ')
        OperatingExpense.objects.filter(pk=self.expense.pk).update(voided_by=self.actor,voided_at=timezone.now(),void_reason='Test void')

    def test_expense_category_unique(self):
        with self.assertRaises((IntegrityError, DataError)):
            with transaction.atomic(): ExpenseCategory.objects.create(name=self.ec.name)

    def test_business_keys_unique(self):
        with self.assertRaises((IntegrityError, DataError)):
            with transaction.atomic(): Product.objects.create(category=self.category,sku=self.product.sku,name='Duplicate',brand='Test',model='Test',selling_price=1)

    def test_admin_blocks_direct_transactions_even_for_superuser(self):
        self.actor.is_staff=True;self.actor.is_superuser=True
        req=RequestFactory().get('/admin/'); req.user=self.actor
        for model in (Sale,SaleItem,Purchase,PurchaseItem,StockMovement,OperatingExpense,AuthorizedUser):
            handler=admin.site._registry[model]
            with self.subTest(model=model.__name__):
                self.assertFalse(handler.has_add_permission(req))
                self.assertFalse(handler.has_change_permission(req))
                self.assertFalse(handler.has_delete_permission(req))
        self.assertIn('cost_price',admin.site._registry[Product].get_readonly_fields(req))
        self.assertIn('current_stock',admin.site._registry[Product].get_readonly_fields(req))

    def test_cashier_cannot_view_cost_bearing_admin(self):
        self.actor.is_staff=True
        req=RequestFactory().get('/admin/'); req.user=self.actor
        for model in (Sale,SaleItem,OperatingExpense,ExpenseCategory,Product):
            with self.subTest(model=model.__name__): self.assertFalse(admin.site._registry[model].has_view_permission(req))

    def test_empty_backfill_preflight_repeat_is_read_only(self):
        guard=import_module('pandoraapp.migrations.0003_database_safeguards').check_existing_data
        before=(Product.objects.count(),get_user_model().objects.count(),StockMovement.objects.count())
        with connection.schema_editor(atomic=False) as editor:
            guard(apps,editor);guard(apps,editor)
        self.assertEqual(before,(Product.objects.count(),get_user_model().objects.count(),StockMovement.objects.count()))

    def test_opening_stock_requires_review_not_invented_cost(self):
        guard=import_module('pandoraapp.migrations.0003_database_safeguards').check_existing_data
        Product.objects.filter(pk=self.product.pk).update(current_stock=5)
        with self.assertRaisesRegex(RuntimeError,'opening_quantity_and_cost_review'):
            with connection.schema_editor(atomic=False) as editor: guard(apps,editor)
        self.product.refresh_from_db(); self.assertEqual(self.product.current_stock,5)
        self.assertEqual(self.product.cost_price,Decimal('0'))

    def test_preflight_rejects_empty_completed_header(self):
        other=Sale.objects.create(receipt_no='TEST-EMPTY',cashier_auth=self.actor,sale_date=date(2026,11,11),status='completed')
        guard=import_module('pandoraapp.migrations.0003_database_safeguards').check_existing_data
        with self.assertRaisesRegex(RuntimeError,'empty completion'):
            with connection.schema_editor(atomic=False) as editor: guard(apps,editor)
        self.assertTrue(Sale.objects.filter(pk=other.pk).exists())


from django.test import TransactionTestCase
from django.db.migrations.executor import MigrationExecutor


class MigrationUpgradeTests(TransactionTestCase):
    def test_existing_cost_and_legacy_actor_are_preserved_without_guessing(self):
        self.assertTrue(connection.settings_dict['NAME'].startswith('pandora_t04_test_'))
        executor = MigrationExecutor(connection)
        executor.migrate([('pandoraapp','0001_initial')])
        old = executor.loader.project_state([('pandoraapp','0001_initial')]).apps
        Cat = old.get_model('pandoraapp','Category')
        Prod = old.get_model('pandoraapp','Product')
        Actor = old.get_model('pandoraapp','AuthorizedUser')
        OldSale = old.get_model('pandoraapp','Sale')
        cat = Cat.objects.create(name='Synthetic migration category')
        prod = Prod.objects.create(category_id=cat.pk,sku='MIGRATION-TEST',name='Test',brand='Test',model='Test',
            cost_price=Decimal('1.23'),selling_price=Decimal('2.34'),current_stock=0,reorder_level=0)
        actor = Actor.objects.create(username='synthetic_legacy',first_name='Test',last_name='Only')
        sale = OldSale.objects.create(receipt_no='MIGRATION-SALE',sale_date=date(2026,11,11),cashier_id=actor.pk,status='completed')
        try:
            executor = MigrationExecutor(connection)
            executor.migrate([('pandoraapp','0002_expand_accounts_costs_expenses')])
            expanded = executor.loader.project_state([('pandoraapp','0002_expand_accounts_costs_expenses')]).apps
            P = expanded.get_model('pandoraapp','Product'); S = expanded.get_model('pandoraapp','Sale')
            self.assertEqual(P.objects.get(pk=prod.pk).cost_price, Decimal('1.230000'))
            preserved = S.objects.get(pk=sale.pk)
            self.assertEqual(preserved.cashier_id,actor.pk)
            self.assertIsNone(preserved.cashier_auth_id)
            guard=import_module('pandoraapp.migrations.0003_database_safeguards').check_existing_data
            with self.assertRaisesRegex(RuntimeError,'sale_completed_cashier'):
                with connection.schema_editor(atomic=False) as editor: guard(expanded,editor)
            self.assertTrue(S.objects.filter(pk=sale.pk).exists())
        finally:
            # These are explicitly synthetic fixtures in the disposable test DB only.
            with connection.cursor() as c:
                c.execute('DELETE FROM pandoraapp_sale WHERE receipt_no=%s',['MIGRATION-SALE'])
            latest = MigrationExecutor(connection)
            latest.migrate(latest.loader.graph.leaf_nodes('pandoraapp'))
