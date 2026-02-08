from django.contrib import admin
from .models import Category, Transaction, Budget


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'category_type', 'user')
    list_filter = ('category_type',)
    search_fields = ('name',)
    ordering = ('category_type', 'name')


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('date', 'transaction_type', 'amount', 'category', 'user')
    list_filter = ('transaction_type', 'category')
    search_fields = ('description',)
    date_hierarchy = 'date'
    ordering = ('-date',)


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ('category', 'monthly_limit', 'month', 'year', 'user')
    list_filter = ('month', 'year')
