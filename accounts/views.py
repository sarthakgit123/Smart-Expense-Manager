from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView, DeleteView
from django.db import IntegrityError
from django.contrib import messages
from django.db.models import Sum
from django.utils.timezone import now
from datetime import date
from calendar import monthrange
from accounts.utils import send_budget_alert
from django.utils.timezone import now





from transactions.models import Category, Transaction, Budget  # <-- IMPORTANT


# ---------------------------
# AUTH VIEWS
# ---------------------------

def register_view(request):
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')

        if password1 == password2:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password1,
                first_name=first_name,
                last_name=last_name
            )
            login(request, user)
            return redirect('accounts:dashboard')

    return render(request, 'accounts/register.html')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)

        if user:
            login(request, user)
            return redirect('accounts:dashboard')

    return render(request, 'accounts/login.html')


@login_required
def logout_view(request):
    logout(request)
    return redirect('accounts:login')


# ---------------------------
# DASHBOARD
# ---------------------------

from datetime import datetime

@login_required
def dashboard_view(request):
    transactions = Transaction.objects.filter(
        user=request.user
    )

    income_total = transactions.filter(
        transaction_type='IN'
    ).aggregate(total=Sum('amount'))['total'] or 0

    expense_total = transactions.filter(
        transaction_type='EX'
    ).aggregate(total=Sum('amount'))['total'] or 0

    # Expense by category (for pie chart)
    expense_by_category = (
        transactions
        .filter(transaction_type='EX')
        .values('category__name')
        .annotate(total=Sum('amount'))
    )

    # Get current month budgets
    now = datetime.now()
    budgets = Budget.objects.filter(
        user=request.user,
        month=now.month,
        year=now.year
    )
    
    # Add calculated fields to budgets
    budget_data = []
    for budget in budgets:
        budget_data.append({
            'category': budget.category,
            'monthly_limit': budget.monthly_limit,
            'spent_amount': budget.get_spent_amount(),
            'remaining_amount': budget.get_remaining(),
            'is_over_budget': budget.is_over_budget()
        })

    context = {
    'transactions': transactions.order_by('-date')[:10],
    'total_income': income_total,
    'total_expense': expense_total,
    'savings': income_total - expense_total,

    'expense_labels': [
        e['category__name'] or 'Uncategorized'
        for e in expense_by_category
    ],
    'expense_data': [
        float(e['total']) for e in expense_by_category
    ],


    'budgets': budgets,
}

    return render(request, 'accounts/dashboard.html', context)


# ---------------------------
# TRANSACTION CRUD (HTML)
# ---------------------------

class TransactionCreateView(CreateView):
    model = Transaction
    fields = ['category', 'transaction_type', 'amount', 'description', 'date']
    template_name = 'accounts/transaction_form.html'
    success_url = reverse_lazy('accounts:dashboard')

    def form_valid(self, form):
        form.instance.user = self.request.user
        response = super().form_valid(form)

        # 🔔 CHECK BUDGET AFTER TRANSACTION
        self.check_budget_alert(form.instance)

        return response

    def check_budget_alert(self, transaction):
        if transaction.transaction_type != 'EX':
            return

        today = transaction.date
        budgets = Budget.objects.filter(
            user=transaction.user,
            category=transaction.category,
            month=today.month,
            year=today.year,
            alert_sent=False
        )

        for budget in budgets:
            spent = budget.get_spent_amount()
            if spent > budget.monthly_limit:
                send_budget_alert(transaction.user, budget, spent)
                budget.alert_sent = True
                budget.save()



class TransactionUpdateView(UpdateView):
    model = Transaction
    fields = ['category', 'transaction_type', 'amount', 'description', 'date']
    template_name = 'accounts/transaction_form.html'
    success_url = reverse_lazy('accounts:dashboard')

    def get_queryset(self):
        return Transaction.objects.filter(user=self.request.user)


class TransactionDeleteView(DeleteView):
    model = Transaction
    template_name = 'accounts/transaction_confirm_delete.html'
    success_url = reverse_lazy('accounts:dashboard')

    def get_queryset(self):
        return Transaction.objects.filter(user=self.request.user)
    
# ---------------------------
# CATEGORY CRUD (HTML)
# ---------------------------

class CategoryCreateView(CreateView):
    model = Category
    fields = ['name', 'category_type']
    template_name = 'accounts/category_form.html'
    success_url = reverse_lazy('accounts:dashboard')

    def form_valid(self, form):
        form.instance.user = self.request.user
        try:
            return super().form_valid(form)
        except IntegrityError:
            messages.error(
                self.request,
                "Category already exists."
            )
            return redirect('accounts:dashboard')


class CategoryUpdateView(UpdateView):
    model = Category
    fields = ['name', 'category_type']
    template_name = 'accounts/category_form.html'
    success_url = reverse_lazy('accounts:dashboard')

    def get_queryset(self):
        return Category.objects.filter(user=self.request.user)


class CategoryDeleteView(DeleteView):
    model = Category
    template_name = 'accounts/category_confirm_delete.html'
    success_url = reverse_lazy('accounts:dashboard')

    def get_queryset(self):
        return Category.objects.filter(user=self.request.user)
    

@login_required
def categories_view(request):
    categories = Category.objects.filter(user=request.user).order_by('category_type', 'name')

    return render(request, 'accounts/categories.html', {
        'categories': categories
    })






@login_required
def monthly_report_view(request):
    current_date = now()
    month = int(request.GET.get('month', current_date.month))
    year = int(request.GET.get('year', current_date.year))

    start_date = date(year, month, 1)
    end_date = date(year, month, monthrange(year, month)[1])

    transactions = Transaction.objects.filter(
        user=request.user,
        date__range=(start_date, end_date)
    )

    income = transactions.filter(
        transaction_type='IN'
    ).aggregate(total=Sum('amount'))['total'] or 0

    expense = transactions.filter(
        transaction_type='EX'
    ).aggregate(total=Sum('amount'))['total'] or 0

    context = {
        'month': month,
        'year': year,
        'income': float(income),
        'expense': float(expense),
        'savings': float(income - expense),
        'transactions': transactions,
    }

    return render(request, 'accounts/monthly_report.html', context)

        
from openpyxl import Workbook
from django.http import HttpResponse
from datetime import date
from calendar import monthrange


@login_required
def monthly_report_excel(request):
    month = int(request.GET.get('month'))
    year = int(request.GET.get('year'))

    start_date = date(year, month, 1)
    end_date = date(year, month, monthrange(year, month)[1])

    transactions = Transaction.objects.filter(
        user=request.user,
        date__range=(start_date, end_date)
    ).select_related('category')

    # Create Excel workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Monthly Report"

    # Header row
    ws.append([
        "Date",
        "Category",
        "Type",
        "Amount",
        "Description"
    ])

    # Data rows
    for t in transactions:
        ws.append([
            t.date.strftime('%Y-%m-%d'),
            t.category.name if t.category else "Uncategorized",
            "Income" if t.transaction_type == "IN" else "Expense",
            float(t.amount),
            t.description or ""
        ])

    # Prepare response
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = (
        f'attachment; filename="monthly_report_{month}_{year}.xlsx"'
    )

    wb.save(response)
    return response

# ---------------------------
# BUDGET CRUD (HTML)
# ---------------------------

class BudgetCreateView(CreateView):
    model = Budget
    fields = ['category', 'monthly_limit', 'month', 'year']
    template_name = 'accounts/budget_form.html'
    success_url = reverse_lazy('accounts:dashboard')

    def form_valid(self, form):
        form.instance.user = self.request.user

        try:
            return super().form_valid(form)
        except IntegrityError:
            messages.error(
                self.request,
                "A budget for this category already exists for the selected month."
            )
            return redirect('accounts:dashboard')

class BudgetUpdateView(UpdateView):
    model = Budget
    fields = ['category', 'monthly_limit', 'month', 'year']
    template_name = 'accounts/budget_form.html'
    success_url = reverse_lazy('accounts:dashboard')

    def get_queryset(self):
        return Budget.objects.filter(user=self.request.user)


class BudgetDeleteView(DeleteView):
    model = Budget
    template_name = 'accounts/budget_confirm_delete.html'
    success_url = reverse_lazy('accounts:dashboard')

    def get_queryset(self):
        return Budget.objects.filter(user=self.request.user)
