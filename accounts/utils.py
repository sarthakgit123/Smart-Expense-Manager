from django.core.mail import send_mail
from django.conf import settings


def send_budget_alert(user, budget, spent):
    subject = "⚠ Budget Limit Exceeded"
    message = (
        f"Hello {user.first_name},\n\n"
        f"You have exceeded your budget for:\n\n"
        f"Category: {budget.category.name}\n"
        f"Budget Limit: ₹{budget.monthly_limit}\n"
        f"Spent: ₹{spent}\n\n"
        f"Please review your expenses.\n\n"
        f"- Finance Tracker"
    )

    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False
    )
