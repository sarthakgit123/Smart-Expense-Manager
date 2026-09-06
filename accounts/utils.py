import threading
import logging
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)


def send_budget_alert(user, budget_id, spent):
    """
    Sends an automated budget alert email to the user's registered email address.
    """
    if not user or not user.email:
        logger.warning("Budget alert not sent: User has no registered email address.")
        return False

    from transactions.models import Budget
    try:
        budget = Budget.objects.select_related('category').get(id=budget_id)
    except Budget.DoesNotExist:
        logger.warning("Budget alert not sent: Budget id %s does not exist.", budget_id)
        return False

    name = user.first_name.strip() if user.first_name else user.username
    category_name = budget.category.name if budget.category else "Uncategorized Expenses"
    limit_val = float(budget.monthly_limit)
    spent_val = float(spent)
    exceeded_by = spent_val - limit_val

    subject = f"🚨 Budget Alert: You have exceeded your budget for {category_name}"

    message = (
        f"Hi {name},\n\n"
        f"This is an automated notification to let you know that your expenses have exceeded "
        f"your monthly budget limit for '{category_name}'.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Budget Details ({budget.month:02d}/{budget.year}):\n"
        f"• Category:         {category_name}\n"
        f"• Monthly Limit:    ₹{limit_val:,.2f}\n"
        f"• Total Spent:      ₹{spent_val:,.2f}\n"
        f"• Exceeded by:      ₹{exceeded_by:,.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Please sign in to your Smart Expense Manager dashboard to review your recent transactions.\n\n"
        f"Best regards,\n"
        f"Smart Expense Manager Team\n"
    )

    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or getattr(settings, 'EMAIL_HOST_USER', None)

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=[user.email],
            fail_silently=False,
        )
        Budget.objects.filter(id=budget.id).update(alert_sent=True)
        logger.info("Budget alert email successfully dispatched to %s for category '%s'.", user.email, category_name)
        return True
    except Exception as e:
        logger.error("Budget alert email delivery failed for %s: %s", user.email, e)
        return False


def send_email_async(func, *args, **kwargs):
    """
    Executes an email sending function asynchronously in a background thread to prevent HTTP blocking.
    """
    thread = threading.Thread(
        target=func,
        args=args,
        kwargs=kwargs,
        daemon=True,
    )
    thread.start()


def check_and_trigger_budget_alerts(user, category, month, year):
    """
    Evaluates budget status for a given user, category, month, and year.
    Dispatches automated email alert if spending exceeds monthly limit and alert_sent is False.
    Resets alert_sent to False if spending drops back below limit (e.g. transaction deletion/edit).
    """
    if not user or not category:
        return

    from transactions.models import Budget
    budgets = Budget.objects.filter(
        user=user,
        category=category,
        month=month,
        year=year,
    )

    for budget in budgets:
        spent = budget.get_spent_amount()
        if spent > budget.monthly_limit:
            if not budget.alert_sent:
                # Trigger automated email to user's registered email
                send_email_async(send_budget_alert, user, budget.id, spent)
        else:
            if budget.alert_sent:
                budget.alert_sent = False
                budget.save(update_fields=['alert_sent'])

