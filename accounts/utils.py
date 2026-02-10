# accounts/utils.py

import threading
import logging
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)


def send_budget_alert(user, budget, spent):
    subject = "🚨 Budget Exceeded Alert"
    message = (
        f"Hi {user.first_name},\n\n"
        f"You have exceeded your budget for {budget.category.name}.\n"
        f"Budget Limit: ₹{budget.monthly_limit}\n"
        f"Spent: ₹{spent}\n\n"
        f"Please review your expenses."
    )

    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
    except Exception as e:
        logger.error("Budget email failed: %s", e)


def send_email_async(func, *args, **kwargs):
    thread = threading.Thread(
        target=func,
        args=args,
        kwargs=kwargs,
        daemon=True,
    )
    thread.start()
