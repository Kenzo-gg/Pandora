from django.urls import path
from . import views
from . import business_views
from . import supplier_views

app_name = 'pandoraapp'
urlpatterns = [path('', views.home, name='home'),
               path('reports/products/', business_views.report, {'kind': 'performance'}, name='performance_report'),
               path('reports/profit/', business_views.report, {'kind': 'profit'}, name='profit_report'),
               path('reports/movements/', business_views.report, {'kind': 'movements'}, name='movement_report'),
               path('expenses/', business_views.expenses, name='expenses'),
               path('expenses/new/', business_views.expense_create, name='expense_create'),
               path('expenses/categories/new/', business_views.expense_category, name='expense_category'),
               path('expenses/<int:pk>/void/', business_views.expense_void, name='expense_void'),
               path('reports/inventory/', views.inventory_report, name='inventory_report'),
               path('reports/sales/', views.sales_report, name='sales_report'),
               path('products/', views.products, name='products'),
               path('inventory/reorder/', views.reorder, name='reorder'),
               path('suppliers/', supplier_views.supplier_list, name='suppliers'),
               path('suppliers/new/', supplier_views.supplier_edit, name='supplier_create'),
               path('suppliers/<int:pk>/', supplier_views.supplier_detail, name='supplier_detail'),
               path('suppliers/<int:pk>/edit/', supplier_views.supplier_edit, name='supplier_edit')]
for kind, plural, action in [('purchase', 'purchases', 'receive'), ('sale', 'sales', 'complete')]:
    urlpatterns += [
        path(f'{plural}/<int:pk>/print/', business_views.transaction_pdf, {'kind': kind}, name=kind + '_pdf'),
        path(f'{plural}/', views.history, {'kind': kind}, name=kind + '_history'),
        path(f'{plural}/new/', views.create, {'kind': kind}, name=kind + '_create'),
        path(f'{plural}/<int:pk>/', views.detail, {'kind': kind}, name=kind + '_detail'),
        path(f'{plural}/<int:pk>/{action}/', views.post_transaction, {'kind': kind}, name=kind + '_post'),
        path(f'{plural}/<int:pk>/cancel/', views.cancel, {'kind': kind}, name=kind + '_cancel'),
    ]
