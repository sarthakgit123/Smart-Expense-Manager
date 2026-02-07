from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView, DeleteView

from transactions.models import Transaction   # <-- IMPORTANT


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

@login_required
def dashboard_view(request):
    transactions = Transaction.objects.filter(
        user=request.user
    ).order_by('-date')

    total_income = sum(
        t.amount for t in transactions if t.transaction_type == 'IN'
    )
    total_expense = sum(
        t.amount for t in transactions if t.transaction_type == 'EX'
    )

    context = {
        'transactions': transactions,
        'total_income': total_income,
        'total_expense': total_expense,
        'savings': total_income - total_expense
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
        return super().form_valid(form)


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

@login_required
def transactions_view(request):
    """Transactions page - list and manage transactions"""
    return render(request, 'accounts/transactions.html')

@login_required
def categories_view(request):
    """Categories page - manage income/expense categories"""
    return render(request, 'accounts/categories.html')

@login_required
def budgets_view(request):
    """Budgets page - manage budgets"""
    return render(request, 'accounts/budgets.html')