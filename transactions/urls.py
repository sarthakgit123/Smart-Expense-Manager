from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CategoryViewSet, TransactionViewSet, BudgetViewSet
from .telegram_views import (
    generate_link_code,
    confirm_link,
    create_telegram_transaction,
    list_telegram_categories,
    telegram_message,
)

router = DefaultRouter()
router.register('categories', CategoryViewSet, basename='category')
router.register('transactions', TransactionViewSet, basename='transaction')
router.register('budgets', BudgetViewSet, basename='budget')

urlpatterns = [
    path('', include(router.urls)),
    path('telegram/link/generate/', generate_link_code, name='telegram-generate-link-code'),
    path('telegram/link/', confirm_link, name='telegram-confirm-link'),
    path('telegram/expense/', create_telegram_transaction, name='telegram-expense'),
    path('telegram/categories/', list_telegram_categories, name='telegram-categories'),
    path('telegram/message/', telegram_message, name='telegram-message'),
]
