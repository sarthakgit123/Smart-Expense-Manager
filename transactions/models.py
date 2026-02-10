from django.db import models
from django.contrib.auth.models import User



class Category(models.Model):
    INCOME = 'IN'
    EXPENSE = 'EX'

    CATEGORY_TYPE_CHOICES = [
        (INCOME, 'Income'),
        (EXPENSE, 'Expense'),
    ]

    # NULL user → global default category
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='categories'
    )

    name = models.CharField(max_length=100)

    category_type = models.CharField(
        max_length=2,
        choices=CATEGORY_TYPE_CHOICES
    )

    # Marks default/global categories
    is_default = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Allows same name for default and user category
        unique_together = ('user', 'name', 'category_type')

    def __str__(self):
        return self.name


class Transaction(models.Model):
    INCOME = 'IN'
    EXPENSE = 'EX'

    TRANSACTION_TYPE_CHOICES = [
        (INCOME, 'Income'),
        (EXPENSE, 'Expense'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='transactions'
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions'
    )
    transaction_type = models.CharField(
        max_length=2,
        choices=TRANSACTION_TYPE_CHOICES
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )
    description = models.TextField(blank=True)
    date = models.DateField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.amount} on {self.date}"

    class Meta:
        ordering = ['-date']


class Budget(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='budgets'
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        limit_choices_to={'category_type': Category.EXPENSE}
    )
    monthly_limit = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )
    month = models.PositiveIntegerField()  # 1–12
    year = models.PositiveIntegerField()

    

    created_at = models.DateTimeField(auto_now_add=True)
    
    alert_sent = models.BooleanField(default=False)

    class Meta:
        unique_together = ('user', 'category', 'month', 'year')

    def __str__(self):
        return f"{self.category.name} - {self.month}/{self.year}"
     
    def get_spent_amount(self):
        """Calculate total spent in this budget period"""
        from django.db.models import Sum
        spent = Transaction.objects.filter(
            user=self.user,
            category=self.category,
            transaction_type='EX',
            date__month=self.month,
            date__year=self.year
        ).aggregate(total=Sum('amount'))['total']
        return spent or 0
    
    def get_remaining(self):
        """Calculate remaining budget"""
        return self.monthly_limit - self.get_spent_amount()
    
    def is_over_budget(self):
        """Check if spending exceeds budget"""
        return self.get_spent_amount() > self.monthly_limit
