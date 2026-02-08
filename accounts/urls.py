from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    # Auth
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Dashboard
    path('dashboard/', views.dashboard_view, name='dashboard'),

    # Transactions (HTML views)
    path('transactions/add/', views.TransactionCreateView.as_view(), name='transaction-add'),
    path('transactions/<int:pk>/edit/', views.TransactionUpdateView.as_view(), name='transaction-edit'),
    path('transactions/<int:pk>/delete/', views.TransactionDeleteView.as_view(), name='transaction-delete'),

    # Categories (HTML views)
    path('categories/', views.categories_view, name='categories'),
    path('categories/add/', views.CategoryCreateView.as_view(), name='category-add'),
    path('categories/<int:pk>/edit/', views.CategoryUpdateView.as_view(), name='category-edit'),
    path('categories/<int:pk>/delete/', views.CategoryDeleteView.as_view(), name='category-delete'),

    path('reports/monthly/', views.monthly_report_view, name='monthly-report'),
    
    # Budgets
    path('budgets/add/', views.BudgetCreateView.as_view(), name='budget-add'),
    path('budgets/<int:pk>/edit/', views.BudgetUpdateView.as_view(), name='budget-edit'),
    path('budgets/<int:pk>/delete/', views.BudgetDeleteView.as_view(), name='budget-delete'),

    path('reports/monthly/excel/', views.monthly_report_excel, name='monthly-report-excel'),




]
