from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView, DeleteView
from django.db import IntegrityError
from django.contrib import messages
from django.db.models import Sum, Q
from django.utils.timezone import now
from datetime import date
from calendar import monthrange
from django.db.models.functions import ExtractMonth
from accounts.utils import send_budget_alert, send_email_async
from transactions.models import Category, Transaction, Budget


# ---------------------------
# AUTH VIEWS
# ---------------------------

def register_view(request):
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        password1 = request.POST.get('password1', '')
        password2 = request.POST.get('password2', '')

        # Validation
        errors = []
        
        if not username or not email or not password1 or not password2:
            errors.append('All fields are required.')
        
        if password1 != password2:
            errors.append('Passwords do not match.')
        
        # Run Django password validators
        if password1:
            try:
                temp_user = User(username=username, email=email, first_name=first_name, last_name=last_name)
                validate_password(password1, user=temp_user)
            except ValidationError as e:
                errors.extend(e.messages)
        
        # Check if username already exists
        if User.objects.filter(username=username).exists():
            errors.append('Username already exists. Please choose a different username.')
        
        # Check if email already exists
        if User.objects.filter(email=email).exists():
            errors.append('Email already registered. Please use a different email.')
        
        if errors:
            # Clear existing messages first
            storage = messages.get_messages(request)
            storage.used = True
            
            # Add new error messages
            for error in errors:
                messages.error(request, error)
            
            context = {
                'username': username,
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
            }
            return render(request, 'accounts/register.html', context)
        
        # Create user
        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password1,
                first_name=first_name,
                last_name=last_name
            )
            # Specify the backend explicitly
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            messages.success(request, f'Welcome {first_name}! Your account has been created.')
            return redirect('accounts:dashboard')
        except IntegrityError:
            messages.error(request, 'An error occurred. Username or email may already exist.')
            return render(request, 'accounts/register.html')
    
    # GET request - clear any old messages
    storage = messages.get_messages(request)
    storage.used = True
    
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
    transactions = Transaction.objects.filter(user=request.user)

    # -------------------------------
    # 🔹 YEAR SELECTION
    # -------------------------------
    selected_year = int(request.GET.get('year', date.today().year))

    # -------------------------------
    # TOTALS
    # -------------------------------
    income_total = transactions.filter(
        transaction_type='IN'
    ).aggregate(total=Sum('amount'))['total'] or 0

    expense_total = transactions.filter(
        transaction_type='EX'
    ).aggregate(total=Sum('amount'))['total'] or 0

    # -------------------------------
    # PIE CHART: Expense by Category
    # -------------------------------
    expense_by_category = (
        transactions
        .filter(transaction_type='EX', date__year=selected_year)
        .values('category__name')
        .annotate(total=Sum('amount'))
    )

    # -------------------------------
    # 🔥 BAR CHART: Monthly Income vs Expense
    # -------------------------------
    monthly_data = (
        transactions
        .filter(date__year=selected_year)
        .annotate(month=ExtractMonth('date'))
        .values('month', 'transaction_type')
        .annotate(total=Sum('amount'))
        .order_by('month')
    )

    monthly_income = [0] * 12
    monthly_expense = [0] * 12

    for item in monthly_data:
        idx = item['month'] - 1
        if item['transaction_type'] == 'IN':
            monthly_income[idx] = float(item['total'])
        else:
            monthly_expense[idx] = float(item['total'])

    # -------------------------------
    # AVAILABLE YEARS (for dropdown)
    # -------------------------------
    years = (
    transactions
    .dates('date', 'year')
    )

    # -------------------------------
    # BUDGETS (Current Month Only)
    # -------------------------------
    today = date.today()
    budgets = Budget.objects.filter(
        user=request.user,
        month=today.month,
        year=today.year
    )

    context = {
        'transactions': transactions.order_by('-date')[:10],

        'total_income': income_total,
        'total_expense': expense_total,
        'savings': income_total - expense_total,

        # PIE CHART
        'expense_labels': [
            e['category__name'] or 'Uncategorized'
            for e in expense_by_category
        ],
        'expense_data': [
            float(e['total']) for e in expense_by_category
        ],

        # BAR CHART
        'monthly_income': monthly_income,
        'monthly_expense': monthly_expense,

        # YEAR SELECT
        'selected_year': selected_year,
        'years': years,

        'budgets': budgets,
    }

    return render(request, 'accounts/dashboard.html', context)


# ---------------------------
# TRANSACTION CRUD (HTML)
# ---------------------------

class TransactionCreateView(LoginRequiredMixin, CreateView):
    model = Transaction
    fields = ['transaction_type', 'category', 'amount', 'description', 'date']
    template_name = 'accounts/transaction_form.html'
    success_url = reverse_lazy('accounts:dashboard')

    def get_initial(self):
        initial = super().get_initial()
        tx_type = self.request.GET.get('transaction_type')
        if tx_type in ['IN', 'EX']:
            initial['transaction_type'] = tx_type
        return initial

    def get_form(self, form_class=None):
        form = super().get_form(form_class)

        tx_type = (
            self.request.GET.get('transaction_type')
            or form.initial.get('transaction_type')
        )

        qs = Category.objects.filter(
            Q(is_default=True) | Q(user=self.request.user)
        )

        if tx_type in ['IN', 'EX']:
            qs = qs.filter(category_type=tx_type)

        form.fields['category'].queryset = qs
        return form

    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)


class TransactionUpdateView(LoginRequiredMixin, UpdateView):
    model = Transaction
    fields = ['transaction_type', 'category', 'amount', 'description', 'date']
    template_name = 'accounts/transaction_form.html'
    success_url = reverse_lazy('accounts:dashboard')

    def get_queryset(self):
        return Transaction.objects.filter(user=self.request.user)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)

        # Filter categories including default categories based on transaction type
        qs = Category.objects.filter(
            Q(is_default=True) | Q(user=self.request.user),
            category_type=self.object.transaction_type
        )

        form.fields['category'].queryset = qs
        return form



class TransactionDeleteView(LoginRequiredMixin, DeleteView):
    model = Transaction
    template_name = 'accounts/transaction_confirm_delete.html'
    success_url = reverse_lazy('accounts:dashboard')

    def get_queryset(self):
        return Transaction.objects.filter(user=self.request.user)

    
# ---------------------------
# CATEGORY CRUD (HTML)
# ---------------------------

class CategoryCreateView(LoginRequiredMixin, CreateView):
    model = Category
    fields = ['name', 'category_type']
    template_name = 'accounts/category_form.html'
    success_url = reverse_lazy('accounts:categories')

    def form_valid(self, form):
        form.instance.user = self.request.user
        try:
            return super().form_valid(form)
        except IntegrityError:
            messages.error(
                self.request,
                "Category already exists."
            )
            return redirect('accounts:category-add')


class CategoryUpdateView(LoginRequiredMixin, UpdateView):
    model = Category
    fields = ['name', 'category_type']
    template_name = 'accounts/category_form.html'
    success_url = reverse_lazy('accounts:categories')

    def get_queryset(self):
        return Category.objects.filter(user=self.request.user)


class CategoryDeleteView(LoginRequiredMixin, DeleteView):
    model = Category
    template_name = 'accounts/category_confirm_delete.html'
    success_url = reverse_lazy('accounts:categories')

    def get_queryset(self):
        return Category.objects.filter(user=self.request.user)
    

@login_required
def categories_view(request):
    categories = Category.objects.filter(
        Q(user=request.user) | Q(is_default=True)
    ).order_by('-is_default', 'category_type', 'name')

    return render(request, 'accounts/categories.html', {
        'categories': categories
    })


@login_required
def monthly_report_view(request):
    current_date = now()
    try:
        month = int(request.GET.get('month', current_date.month))
        year = int(request.GET.get('year', current_date.year))
    except (ValueError, TypeError):
        month, year = current_date.month, current_date.year

    start_date = date(year, month, 1)
    end_date = date(year, month, monthrange(year, month)[1])

    transactions = Transaction.objects.filter(
        user=request.user,
        date__range=(start_date, end_date)
    )

    # -----------------------
    # Totals
    # -----------------------
    income = transactions.filter(
        transaction_type='IN'
    ).aggregate(total=Sum('amount'))['total'] or 0

    expense = transactions.filter(
        transaction_type='EX'
    ).aggregate(total=Sum('amount'))['total'] or 0

    # -----------------------
    # Category-wise Expense (Pie Chart)
    # -----------------------
    expense_by_category = (
        transactions
        .filter(transaction_type='EX')
        .values('category__name')
        .annotate(total=Sum('amount'))
    )

    months_list = [
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December')
    ]

    all_tx_years = Transaction.objects.filter(user=request.user).dates('date', 'year')
    available_years = sorted(list({y.year for y in all_tx_years} | {current_date.year}))

    # -----------------------
    # Context
    # -----------------------
    context = {
        'month': month,
        'year': year,
        'months_list': months_list,
        'available_years': available_years,
        'income': float(income),
        'expense': float(expense),
        'savings': float(income - expense),
        'transactions': transactions,

        # Pie chart data
        'expense_category_labels': [
            e['category__name'] or 'Uncategorized'
            for e in expense_by_category
        ],
        'expense_category_data': [
            float(e['total']) for e in expense_by_category
        ],
    }

    return render(request, 'accounts/monthly_report.html', context)


        
from openpyxl import Workbook
from django.http import HttpResponse


@login_required
def monthly_report_excel(request):
    today = date.today()
    try:
        month = int(request.GET.get('month', today.month))
        year = int(request.GET.get('year', today.year))
    except (ValueError, TypeError):
        month, year = today.month, today.year

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

class BudgetCreateView(LoginRequiredMixin, CreateView):
    model = Budget
    fields = ['category', 'monthly_limit', 'month', 'year']
    template_name = 'accounts/budget_form.html'
    success_url = reverse_lazy('accounts:dashboard')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields['category'].queryset = Category.objects.filter(
            Q(is_default=True) | Q(user=self.request.user),
            category_type=Category.EXPENSE
        )
        return form

    def form_valid(self, form):
        form.instance.user = self.request.user

        try:
            return super().form_valid(form)
        except IntegrityError:
            messages.error(
                self.request,
                "A budget for this category already exists for the selected month."
            )
            return redirect('accounts:budget-add')


class BudgetUpdateView(LoginRequiredMixin, UpdateView):
    model = Budget
    fields = ['category', 'monthly_limit', 'month', 'year']
    template_name = 'accounts/budget_form.html'
    success_url = reverse_lazy('accounts:dashboard')

    def get_queryset(self):
        return Budget.objects.filter(user=self.request.user)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields['category'].queryset = Category.objects.filter(
            Q(is_default=True) | Q(user=self.request.user),
            category_type=Category.EXPENSE
        )
        return form


class BudgetDeleteView(LoginRequiredMixin, DeleteView):
    model = Budget
    template_name = 'accounts/budget_confirm_delete.html'
    success_url = reverse_lazy('accounts:dashboard')

    def get_queryset(self):
        return Budget.objects.filter(user=self.request.user)
