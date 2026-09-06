from rest_framework import serializers
from django.db.models import Q
from .models import Category, Transaction, Budget


class CategorySerializer(serializers.ModelSerializer):
    category_type_display = serializers.CharField(
        source='get_category_type_display',
        read_only=True
    )

    class Meta:
        model = Category
        fields = [
            'id',
            'name',
            'category_type',
            'category_type_display',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class TransactionSerializer(serializers.ModelSerializer):
    transaction_type_display = serializers.CharField(
        source='get_transaction_type_display',
        read_only=True
    )
    category_name = serializers.CharField(
        source='category.name',
        read_only=True
    )

    class Meta:
        model = Transaction
        fields = [
            'id',
            'category',
            'category_name',
            'transaction_type',
            'transaction_type_display',
            'amount',
            'description',
            'date',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            self.fields['category'].queryset = Category.objects.filter(
                Q(is_default=True) | Q(user=request.user)
            )

    def validate(self, data):
        category = data.get('category')
        transaction_type = data.get('transaction_type')

        if category and transaction_type:
            if category.category_type != transaction_type:
                raise serializers.ValidationError(
                    "Transaction type must match category type."
                )

        return data


class BudgetSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(
        source='category.name',
        read_only=True
    )

    class Meta:
        model = Budget
        fields = [
            'id',
            'category',
            'category_name',
            'monthly_limit',
            'month',
            'year',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            self.fields['category'].queryset = Category.objects.filter(
                Q(is_default=True) | Q(user=request.user),
                category_type=Category.EXPENSE
            )

