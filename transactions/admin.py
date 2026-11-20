from django.contrib import admin
from .models import Category, Transaction, Budget, TelegramLink, TelegramLinkCode, TelegramMessage


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


@admin.register(TelegramLink)
class TelegramLinkAdmin(admin.ModelAdmin):
    list_display = ('user', 'telegram_user_id', 'telegram_username', 'linked_at')
    search_fields = ('user__username', 'telegram_username', 'telegram_user_id')
    readonly_fields = ('linked_at',)


@admin.register(TelegramLinkCode)
class TelegramLinkCodeAdmin(admin.ModelAdmin):
    # Codes are secrets-in-flight: view-only, and the code itself is not listed.
    list_display = ('user', 'created_at', 'expires_at', 'used')
    list_filter = ('used',)
    search_fields = ('user__username',)
    exclude = ('code',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(TelegramMessage)
class TelegramMessageAdmin(admin.ModelAdmin):
    list_display = ('telegram_user_id', 'message_id', 'transaction', 'processed_at')
    search_fields = ('telegram_user_id', 'message_id')
    readonly_fields = ('processed_at',)
