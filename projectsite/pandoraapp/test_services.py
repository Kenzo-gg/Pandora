"""Synthetic tests only. Run with Django's test runner on a separate MySQL DB."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
import threading
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection, connections
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature

from .models import Category, Product, Supplier, Purchase, Sale, StockMovement
from . import services as s
from .stock_queries import products_needing_reorder, reorder_report

TODAY = date(2026, 11, 12)


class Fixtures:
    def make_fixtures(self):
        # These people, products and money are fictional fixtures in the test DB.
        self.admin = get_user_model().objects.create_user(username='test_admin', password=None,
            is_staff=True, is_superuser=True)
        self.category = Category.objects.create(name='Synthetic keyboards')
        self.supplier = Supplier.objects.create(name='Synthetic supplier', contact_person='Test', contact_number='TEST')
        self.product = Product.objects.create(category=self.category, preferred_supplier=self.supplier,
            sku='TEST-KB', name='Synthetic keyboard', brand='Test', model='Test',
            selling_price=Decimal('450'), reorder_level=5)
        self.serial = 0

    def reference(self, prefix):
        self.serial += 1
        return f'{prefix}-{self.serial}'

    def purchase(self, quantity=10, cost='200.00', *, product=None, lines=None):
        product = product or self.product
        return s.create_purchase_draft(actor=self.admin, reference_no=self.reference('P'),
            supplier_id=self.supplier.pk, order_date=TODAY,
            lines=lines or [dict(product_id=product.pk, quantity=quantity, unit_cost=cost)])

    def receive(self, purchase):
        return s.receive_purchase(actor=self.admin, purchase_id=purchase.pk,
            expected_lines=s.purchase_snapshot(actor=self.admin, purchase_id=purchase.pk))

    def sale(self, quantity=3, *, actor=None, lines=None):
        return s.create_sale_draft(actor=actor or self.admin, receipt_no=self.reference('S'), sale_date=TODAY,
            lines=lines or [dict(product_id=self.product.pk, quantity=quantity)])

    def complete(self, sale, paid='1500.00', *, actor=None, method='cash', snapshot=None):
        user = actor or self.admin
        return s.complete_sale(actor=user, sale_id=sale.pk,
            expected_lines=snapshot if snapshot is not None else s.sale_snapshot(actor=user, sale_id=sale.pk),
            payment_method=method, amount_paid=paid)

    def role_user(self, name, role, codes):
        user = get_user_model().objects.create_user(username=name, password=None)
        group, _ = Group.objects.get_or_create(name=role)
        group.permissions.add(*Permission.objects.filter(content_type__app_label='pandoraapp',codename__in=codes))
        user.groups.add(group)
        return user


class StockServicesTests(Fixtures, TestCase):
    def setUp(self):
        self.make_fixtures()

    def test_drafts_do_not_change_stock_or_create_movements(self):
        p, sale = self.purchase(), self.sale()
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, 0)
        self.assertEqual(self.product.cost_price, 0)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(p.created_by_auth, self.admin)
        self.assertEqual(sale.cashier_auth, self.admin)
        self.assertEqual(sale.items.get().unit_cost_at_sale, 0)

    def test_purchase_weighted_average(self):
        self.receive(self.purchase())
        self.receive(self.purchase(5, '260'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, 15)
        self.assertEqual(self.product.cost_price, Decimal('220.000000'))
        self.assertEqual(list(StockMovement.objects.order_by('pk').values_list('stock_after',flat=True)), [10,15])

    def test_sale_total_change_cost_and_history(self):
        self.receive(self.purchase(10))
        self.receive(self.purchase(5,'260'))
        sale = self.complete(self.sale())
        self.product.refresh_from_db()
        self.assertEqual((sale.total_amount,sale.amount_paid,sale.change_amount), (1350,1500,150))
        self.assertEqual((self.product.current_stock,self.product.cost_price), (12,Decimal('220.000000')))
        self.assertEqual(sale.items.get().unit_cost_at_sale,Decimal('220.000000'))
        movement = StockMovement.objects.get(sale_item__sale=sale)
        self.assertEqual((movement.quantity_change,movement.stock_after,movement.product_id),(-3,12,self.product.pk))
        self.assertEqual(movement.performed_by_auth,self.admin)
        self.assertIsNone(movement.purchase_item_id)

    def test_repeated_receipt_does_not_post_again_or_change_time(self):
        purchase = self.purchase()
        first = self.receive(purchase)
        second = self.receive(purchase)
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock,10)
        self.assertEqual(first.received_at,second.received_at)
        self.assertEqual(StockMovement.objects.count(),1)

    def test_repeated_sale_does_not_post_again(self):
        self.receive(self.purchase())
        sale = self.sale()
        first, second = self.complete(sale), self.complete(sale)
        self.product.refresh_from_db()
        self.assertEqual(first.pk,second.pk)
        self.assertEqual(self.product.current_stock,7)
        self.assertEqual(StockMovement.objects.filter(movement_type='sale').count(),1)
        with self.assertRaises(s.StockError): self.complete(sale,'1600')

    def test_same_reference_same_payload_returns_same_purchase(self):
        args=dict(actor=self.admin,reference_no='stable-p',supplier_id=self.supplier.pk,order_date=TODAY,
            lines=[dict(product_id=self.product.pk,quantity=2,unit_cost='3.50')])
        p = s.create_purchase_draft(**args)
        self.assertEqual(s.create_purchase_draft(**args).pk,p.pk)
        args['lines'][0]['quantity']=3
        with self.assertRaises(s.StockError): s.create_purchase_draft(**args)
        self.assertEqual(Purchase.objects.count(),1)

    def test_same_receipt_same_payload_and_server_price(self):
        args=dict(actor=self.admin,receipt_no='stable-s',sale_date=TODAY,
            lines=[dict(product_id=self.product.pk,quantity=1)])
        sale=s.create_sale_draft(**args)
        Product.objects.filter(pk=self.product.pk).update(selling_price=999)
        self.assertEqual(s.create_sale_draft(**args).pk,sale.pk)
        self.assertEqual(sale.items.get().unit_price,450)
        args['lines'][0]['quantity']=2
        with self.assertRaises(s.StockError): s.create_sale_draft(**args)

    def test_browser_cannot_supply_sale_price_or_cost(self):
        for field in ('unit_price','unit_cost_at_sale','total_amount'):
            with self.subTest(field=field),self.assertRaises(s.StockError):
                self.sale(lines=[dict(product_id=self.product.pk,quantity=1,**{field:'0.01'})])
        self.assertEqual(Sale.objects.count(),0)

    def test_insufficient_stock_rejects_whole_sale(self):
        self.receive(self.purchase(2))
        sale=self.sale(3)
        with self.assertRaises(s.StockError): self.complete(sale)
        sale.refresh_from_db();self.product.refresh_from_db()
        self.assertEqual(sale.status,'pending')
        self.assertEqual(self.product.current_stock,2)
        self.assertEqual(StockMovement.objects.filter(movement_type='sale').count(),0)
        self.assertEqual(sale.items.get().unit_cost_at_sale,0)

    def test_repeated_product_sale_lines_check_combined_stock(self):
        self.receive(self.purchase(5))
        sale=self.sale(lines=[dict(product_id=self.product.pk,quantity=3)]*2)
        with self.assertRaises(s.StockError): self.complete(sale,'3000')
        self.product.refresh_from_db();self.assertEqual(self.product.current_stock,5)

    def test_multiple_sale_lines_record_intermediate_stock(self):
        self.receive(self.purchase(10))
        sale=self.sale(lines=[dict(product_id=self.product.pk,quantity=2),dict(product_id=self.product.pk,quantity=3)])
        self.complete(sale,'2500')
        self.assertEqual(list(StockMovement.objects.filter(sale_item__sale=sale).order_by('pk').values_list('stock_after',flat=True)),[8,5])

    def test_receipt_groups_costs_and_keeps_intermediate_stock(self):
        p=self.purchase(lines=[dict(product_id=self.product.pk,quantity=2,unit_cost='3'),
                              dict(product_id=self.product.pk,quantity=1,unit_cost='8')])
        p=self.receive(p);self.product.refresh_from_db()
        self.assertEqual(p.total_cost,14)
        self.assertEqual(self.product.cost_price,Decimal('4.666667'))
        self.assertEqual(list(StockMovement.objects.order_by('pk').values_list('stock_after',flat=True)),[2,3])

    def test_zero_stock_old_average_does_not_affect_new_receipt(self):
        Product.objects.filter(pk=self.product.pk).update(cost_price=999)
        self.receive(self.purchase(2,'7'))
        self.product.refresh_from_db();self.assertEqual(self.product.cost_price,7)

    def test_card_and_mobile_require_exact_payment(self):
        self.receive(self.purchase(3))
        for method in ('credit_card','mobile_payment'):
            sale=self.sale(1)
            with self.assertRaises(s.StockError): self.complete(sale,'500',method=method)
            self.assertEqual(self.complete(sale,'450',method=method).change_amount,0)

    def test_cash_underpayment_invalid_method_or_money(self):
        self.receive(self.purchase(10));sale=self.sale(1)
        for paid in ('449','NaN','Infinity','-1','450.001','100000000',450.0,True):
            with self.subTest(paid=repr(paid)),self.assertRaises(s.StockError): self.complete(sale,paid)
        with self.assertRaises(s.StockError): self.complete(sale,'450',method='unknown')

    def test_invalid_quantity_empty_lines_date_or_reference(self):
        for value in (0,-1,True,1.5,2147483648):
            with self.subTest(value=value),self.assertRaises(s.StockError): self.purchase(value)
        with self.assertRaises(s.StockError):
            s.create_sale_draft(actor=self.admin,receipt_no='BAD',sale_date=TODAY,lines=[])
        with self.assertRaises(s.StockError):
            s.create_sale_draft(actor=self.admin,receipt_no='BAD SPACE',sale_date=TODAY,lines=[dict(product_id=self.product.pk,quantity=1)])
        with self.assertRaises(s.StockError):
            s.create_sale_draft(actor=self.admin,receipt_no='BAD-DATE',sale_date='2026-99-99',lines=[dict(product_id=self.product.pk,quantity=1)])

    def test_invalid_purchase_money_and_total_overflow(self):
        for value in ('NaN','Infinity','-1','0.001','100000000',1.0):
            with self.subTest(value=value),self.assertRaises(s.StockError): self.purchase(cost=value)
        with self.assertRaises(s.StockError): self.purchase(2,'99999999.99')
        self.assertEqual(Purchase.objects.count(),0)

    def test_stock_overflow_rejects_receipt(self):
        p=self.purchase(1,'1')
        Product.objects.filter(pk=self.product.pk).update(current_stock=2147483647)
        with self.assertRaises(s.StockError): self.receive(p)
        self.assertEqual(StockMovement.objects.count(),0)
        p.refresh_from_db();self.assertEqual(p.status,'pending')

    def test_inactive_or_missing_product_supplier(self):
        Product.objects.filter(pk=self.product.pk).update(is_active=False)
        with self.assertRaises(s.StockError): self.purchase()
        with self.assertRaises(s.StockError): self.sale()
        Product.objects.filter(pk=self.product.pk).update(is_active=True)
        p=self.purchase()
        Supplier.objects.filter(pk=self.supplier.pk).update(is_active=False)
        with self.assertRaises(s.StockError): self.receive(p)
        with self.assertRaises(s.StockError): self.purchase()
        with self.assertRaises(s.StockError): self.sale(lines=[dict(product_id=999999,quantity=1)])

    def test_receipt_failure_rolls_everything_back(self):
        p=self.purchase(lines=[dict(product_id=self.product.pk,quantity=1,unit_cost='2')]*2)
        real=StockMovement.objects.create;calls=[]
        def fail(**kwargs):
            calls.append(1)
            if len(calls)==2: raise RuntimeError('Synthetic failure halfway through receipt')
            return real(**kwargs)
        with patch('pandoraapp.services.StockMovement.objects.create',side_effect=fail):
            with self.assertRaises(RuntimeError): self.receive(p)
        p.refresh_from_db();self.product.refresh_from_db()
        self.assertEqual(p.status,'pending');self.assertIsNone(p.received_at)
        self.assertEqual((self.product.current_stock,self.product.cost_price),(0,0))
        self.assertEqual(StockMovement.objects.count(),0)

    def test_sale_failure_rolls_back_snapshots_movements_and_header(self):
        self.receive(self.purchase(10))
        sale=self.sale(lines=[dict(product_id=self.product.pk,quantity=1)]*2)
        real=StockMovement.objects.create;calls=[]
        def fail(**kwargs):
            calls.append(1)
            if len(calls)==2: raise RuntimeError('Synthetic sale failure')
            return real(**kwargs)
        with patch('pandoraapp.services.StockMovement.objects.create',side_effect=fail):
            with self.assertRaises(RuntimeError): self.complete(sale)
        sale.refresh_from_db();self.product.refresh_from_db()
        self.assertEqual(sale.status,'pending');self.assertEqual(self.product.current_stock,10)
        self.assertEqual(StockMovement.objects.filter(movement_type='sale').count(),0)
        self.assertEqual(list(sale.items.values_list('unit_cost_at_sale',flat=True)),[0,0])

    def test_empty_header_and_pending_history_are_rejected(self):
        sale=Sale.objects.create(receipt_no='EMPTY',sale_date=TODAY,cashier_auth=self.admin)
        with self.assertRaises(s.StockError): self.complete(sale)
        p=self.purchase()
        StockMovement.objects.create(product=self.product,movement_type='purchase',quantity_change=10,
            stock_after=10,purchase_item=p.items.get(),performed_by_auth=self.admin)
        with self.assertRaises(s.StockError): self.receive(p)

    def test_editing_drafts_invalidates_old_snapshot_and_preserves_agreed_price(self):
        sale=self.sale(1);old=s.sale_snapshot(actor=self.admin,sale_id=sale.pk)
        Product.objects.filter(pk=self.product.pk).update(selling_price=999)
        s.replace_sale_lines(actor=self.admin,sale_id=sale.pk,expected_lines=old,
            lines=[dict(product_id=self.product.pk,quantity=2)])
        self.assertEqual(sale.items.get().unit_price,450)
        with self.assertRaises(s.StockError): self.complete(sale,snapshot=old)
        p=self.purchase();old=s.purchase_snapshot(actor=self.admin,purchase_id=p.pk)
        s.replace_purchase_lines(actor=self.admin,purchase_id=p.pk,expected_lines=old,
            lines=[dict(product_id=self.product.pk,quantity=1,unit_cost='5')])
        with self.assertRaises(s.StockError): s.receive_purchase(actor=self.admin,purchase_id=p.pk,expected_lines=old)

    def test_posted_lines_cannot_be_edited_or_cancelled(self):
        p=self.receive(self.purchase())
        with self.assertRaises(s.StockError): s.cancel_purchase(actor=self.admin,purchase_id=p.pk,reason='No')
        with self.assertRaises(s.StockError): s.replace_purchase_lines(actor=self.admin,purchase_id=p.pk,
            lines=[dict(product_id=self.product.pk,quantity=1,unit_cost='1')],expected_lines=s.purchase_snapshot(actor=self.admin,purchase_id=p.pk))
        sale=self.complete(self.sale())
        with self.assertRaises(s.StockError): s.cancel_sale(actor=self.admin,sale_id=sale.pk,reason='No')
        with self.assertRaises(s.StockError): s.replace_sale_lines(actor=self.admin,sale_id=sale.pk,
            lines=[dict(product_id=self.product.pk,quantity=1)],expected_lines=s.sale_snapshot(actor=self.admin,sale_id=sale.pk))

    def test_cancellation_has_metadata_no_stock_and_stable_retry(self):
        p,sale=self.purchase(),self.sale()
        p=s.cancel_purchase(actor=self.admin,purchase_id=p.pk,reason='Not needed')
        sale=s.cancel_sale(actor=self.admin,sale_id=sale.pk,reason='Customer changed mind')
        self.assertIsNone(p.received_at);self.assertIsNotNone(sale.voided_at)
        self.assertEqual(sale.voided_by_auth,self.admin)
        self.assertEqual(s.cancel_sale(actor=self.admin,sale_id=sale.pk,reason='Customer changed mind').voided_at,sale.voided_at)
        self.assertEqual(s.cancel_purchase(actor=self.admin,purchase_id=p.pk,reason='Not needed').remarks,p.remarks)
        with self.assertRaises(s.StockError): s.cancel_sale(actor=self.admin,sale_id=sale.pk,reason='Different')
        with self.assertRaises(s.StockError): s.cancel_purchase(actor=self.admin,purchase_id=p.pk,reason='Different')
        with self.assertRaises(s.StockError): self.receive(p)
        with self.assertRaises(s.StockError): self.complete(sale)
        self.assertEqual(StockMovement.objects.count(),0)

    def test_blank_cancellation_reason_is_rejected(self):
        sale=self.sale()
        with self.assertRaises(s.StockError): s.cancel_sale(actor=self.admin,sale_id=sale.pk,reason='  ')

    def test_roles_permissions_and_ownership(self):
        inventory=self.role_user('test_inventory','Inventory Staff',['add_purchase','change_purchase','view_product'])
        cashier=self.role_user('test_cashier','Cashier',['add_sale','change_sale'])
        other=self.role_user('test_other_cashier','Cashier',['add_sale','change_sale'])
        p=s.create_purchase_draft(actor=inventory,reference_no='INV',supplier_id=self.supplier.pk,order_date=TODAY,
            lines=[dict(product_id=self.product.pk,quantity=3,unit_cost='2')])
        s.receive_purchase(actor=inventory,purchase_id=p.pk,expected_lines=s.purchase_snapshot(actor=inventory,purchase_id=p.pk))
        sale=self.sale(1,actor=cashier)
        with self.assertRaises(PermissionDenied): self.complete(sale,'450',actor=other)
        with self.assertRaises(PermissionDenied): self.sale(actor=inventory)
        with self.assertRaises(PermissionDenied): s.purchase_snapshot(actor=cashier,purchase_id=p.pk)
        with self.assertRaises(PermissionDenied): reorder_report(actor=cashier)
        self.assertIsInstance(reorder_report(actor=inventory),list)
        self.complete(sale,'450',actor=cashier)
        self.assertEqual(StockMovement.objects.get(sale_item__sale=sale).performed_by_auth,cashier)

    def test_role_alone_or_permission_alone_does_not_grant_access(self):
        role_only=self.role_user('role_only','Cashier',[])
        perm_only=get_user_model().objects.create_user(username='perm_only',password=None)
        perm_only.user_permissions.add(Permission.objects.get(content_type__app_label='pandoraapp',codename='add_sale'))
        for user in (role_only,perm_only):
            with self.assertRaises(PermissionDenied): self.sale(actor=user)

    def test_inactive_account_is_rechecked_even_if_caller_object_is_stale(self):
        get_user_model().objects.filter(pk=self.admin.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied): self.purchase()
        with self.assertRaises(PermissionDenied): self.sale()

    def test_anonymous_user_is_rejected(self):
        from django.contrib.auth.models import AnonymousUser
        with self.assertRaises(PermissionDenied): self.sale(actor=AnonymousUser())

    def test_admin_completion_records_actual_operator(self):
        cashier=self.role_user('draft_cashier','Cashier',['add_sale','change_sale'])
        self.receive(self.purchase())
        sale=self.sale(1,actor=cashier)
        result=self.complete(sale,'450')
        self.assertEqual(result.cashier_auth,self.admin)

    def test_reorder_threshold_stockouts_and_inactive_products(self):
        self.assertIn(self.product,list(products_needing_reorder()))
        Product.objects.filter(pk=self.product.pk).update(current_stock=5)
        self.assertIn(self.product,list(products_needing_reorder()))
        Product.objects.filter(pk=self.product.pk).update(current_stock=6)
        self.assertNotIn(self.product,list(products_needing_reorder()))
        Product.objects.filter(pk=self.product.pk).update(current_stock=0,is_active=False)
        self.assertNotIn(self.product,list(products_needing_reorder()))

    def test_reorder_report_excludes_financial_fields(self):
        report=reorder_report(actor=self.admin)
        self.assertEqual(set(report[0]),{'id','sku','name','current_stock','reorder_level','preferred_supplier__name'})

    def test_nested_transaction_leaves_deadlock_retry_to_outer_owner(self):
        from django.db import OperationalError
        with patch('pandoraapp.services._products',side_effect=OperationalError(1213,'synthetic deadlock')):
            with self.assertRaises(OperationalError): self.purchase()
        self.assertEqual(Purchase.objects.count(),0)


class ConcurrentStockTests(Fixtures, TransactionTestCase):
    def setUp(self):
        self.make_fixtures()

    def parallel(self, first, second):
        barrier=threading.Barrier(2,timeout=8)
        def worker(action):
            close_old_connections()
            try:
                # Bound lock waits even if this test fails.
                with connection.cursor() as c: c.execute('SET SESSION innodb_lock_wait_timeout=3')
                barrier.wait()
                try: return ('ok',action().pk)
                except s.StockError: return ('rejected',None)
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(worker,first),pool.submit(worker,second)]
            return [f.result(timeout=25) for f in futures]

    def assert_balances_reconcile(self):
        self.product.refresh_from_db()
        movements=list(StockMovement.objects.filter(product=self.product).order_by('pk'))
        balance=0
        for m in movements:
            balance += m.quantity_change
            self.assertEqual(m.stock_after,balance)
            self.assertGreaterEqual(balance,0)
            if m.sale_item_id:
                self.assertEqual(m.product_id,m.sale_item.product_id)
                self.assertEqual(m.quantity_change,-m.sale_item.quantity)
                self.assertEqual(m.sale_item.sale.status,'completed')
            if m.purchase_item_id:
                self.assertEqual(m.product_id,m.purchase_item.product_id)
                self.assertEqual(m.quantity_change,m.purchase_item.quantity)
                self.assertEqual(m.purchase_item.purchase.status,'completed')
        self.assertEqual(self.product.current_stock,balance)

    def test_deadlock_retry_restarts_whole_transaction(self):
        from django.db import OperationalError
        with patch('pandoraapp.services._products',side_effect=[OperationalError(1213,'synthetic deadlock'),{self.product.pk:self.product}]),patch('pandoraapp.services.time.sleep'):
            p=self.purchase()
        self.assertEqual(Purchase.objects.count(),1)
        self.assertEqual(p.items.count(),1)

    @skipUnlessDBFeature('has_select_for_update')
    def test_two_sales_for_final_unit_only_one_succeeds(self):
        self.receive(self.purchase(1))
        a,b=self.sale(1),self.sale(1)
        results=self.parallel(lambda:self.complete(a,'450'),lambda:self.complete(b,'450'))
        self.assertEqual(sorted(x[0] for x in results),['ok','rejected'])
        self.assert_balances_reconcile();self.assertEqual(self.product.current_stock,0)

    @skipUnlessDBFeature('has_select_for_update')
    def test_simultaneous_duplicate_sale_posts_once(self):
        self.receive(self.purchase(2));sale=self.sale(1)
        results=self.parallel(lambda:self.complete(sale,'450'),lambda:self.complete(sale,'450'))
        self.assertEqual([x[0] for x in results],['ok','ok'])
        self.assertEqual(StockMovement.objects.filter(movement_type='sale').count(),1)
        self.assert_balances_reconcile()

    @skipUnlessDBFeature('has_select_for_update')
    def test_simultaneous_duplicate_receipt_posts_once(self):
        p=self.purchase(3)
        results=self.parallel(lambda:self.receive(p),lambda:self.receive(p))
        self.assertEqual([x[0] for x in results],['ok','ok'])
        self.assertEqual(StockMovement.objects.count(),1)
        self.assert_balances_reconcile();self.assertEqual(self.product.current_stock,3)

    @skipUnlessDBFeature('has_select_for_update')
    def test_simultaneous_receipts_produce_correct_average(self):
        a,b=self.purchase(2,'3'),self.purchase(1,'9')
        results=self.parallel(lambda:self.receive(a),lambda:self.receive(b))
        self.assertEqual([x[0] for x in results],['ok','ok'])
        self.assert_balances_reconcile()
        self.assertEqual((self.product.current_stock,self.product.cost_price),(3,Decimal('5.000000')))

    @skipUnlessDBFeature('has_select_for_update')
    def test_receipt_racing_sale_uses_one_of_two_legal_cost_snapshots(self):
        self.receive(self.purchase(2,'10'))
        p=self.purchase(2,'20');sale=self.sale(1)
        results=self.parallel(lambda:self.receive(p),lambda:self.complete(sale,'450'))
        self.assertEqual([x[0] for x in results],['ok','ok'])
        self.assert_balances_reconcile()
        cost=sale.items.get().unit_cost_at_sale
        self.assertIn(cost,[Decimal('10.000000'),Decimal('15.000000')])
        expected_average=Decimal('16.666667') if cost==10 else Decimal('15.000000')
        self.assertEqual((self.product.current_stock,self.product.cost_price),(3,expected_average))

    @skipUnlessDBFeature('has_select_for_update')
    def test_cancellation_racing_sale_has_one_legal_outcome(self):
        self.receive(self.purchase(1));sale=self.sale(1)
        results=self.parallel(lambda:s.cancel_sale(actor=self.admin,sale_id=sale.pk,reason='Changed mind'),
                              lambda:self.complete(sale,'450'))
        self.assertEqual(sorted(x[0] for x in results),['ok','rejected'])
        sale.refresh_from_db();self.assertIn(sale.status,['completed','cancelled'])
        self.assert_balances_reconcile()
        self.assertEqual(self.product.current_stock,0 if sale.status=='completed' else 1)

    @skipUnlessDBFeature('has_select_for_update')
    def test_draft_edit_racing_completion_cannot_post_changed_items(self):
        self.receive(self.purchase(3));sale=self.sale(1)
        old=s.sale_snapshot(actor=self.admin,sale_id=sale.pk)
        results=self.parallel(lambda:s.replace_sale_lines(actor=self.admin,sale_id=sale.pk,expected_lines=old,
            lines=[dict(product_id=self.product.pk,quantity=2)]),
            lambda:self.complete(sale,'450',snapshot=old))
        self.assertEqual(sorted(x[0] for x in results),['ok','rejected'])
        sale.refresh_from_db();self.assert_balances_reconcile()
        if sale.status=='completed': self.assertEqual((sale.items.get().quantity,self.product.current_stock),(1,2))
        else: self.assertEqual((sale.status,sale.items.get().quantity,self.product.current_stock),('pending',2,3))
