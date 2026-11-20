"""
Business logic shared by the Telegram/n8n endpoints.

Views stay thin (HTTP parsing + auth); everything that touches the database for
the bot lives here so the JSON endpoints and the chat-message endpoint behave
identically.
"""
import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from django.db import IntegrityError, OperationalError, transaction as db_transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .models import Budget, Category, TelegramLink, TelegramLinkCode, TelegramMessage, Transaction
from .telegram_parser import format_inr

FALLBACK_CATEGORY = {
    Transaction.EXPENSE: 'Miscellaneous',
    Transaction.INCOME: 'Other Income',
}


# ---------------------------------------------------------------------------
# Linking
# ---------------------------------------------------------------------------

@dataclass
class LinkResult:
    ok: bool
    status: int
    error: str = ''
    user: object = None


def link_account(telegram_user_id: int, telegram_username: str, code_value: str) -> LinkResult:
    """Consume a one-time code and link the Telegram ID to its Django user."""
    code_value = (code_value or '').strip().upper()
    if not code_value:
        return LinkResult(False, 400, 'code is required')
    try:
        with db_transaction.atomic():
            try:
                link_code = TelegramLinkCode.objects.select_for_update().select_related('user').get(code=code_value)
            except TelegramLinkCode.DoesNotExist:
                return LinkResult(False, 404, 'Invalid or expired code')
            if not link_code.user.is_active:
                return LinkResult(False, 403, 'This account is inactive.')
            if not link_code.is_valid():
                return LinkResult(False, 400, 'Code has expired or already been used')

            # Never transfer a Telegram identity away from another Django account implicitly.
            if TelegramLink.objects.filter(telegram_user_id=telegram_user_id).exclude(user=link_code.user).exists():
                return LinkResult(False, 409, 'This Telegram account is already linked to another account.')

            link_code.used = True
            link_code.save(update_fields=['used'])
            TelegramLink.objects.update_or_create(
                user=link_code.user,
                defaults={'telegram_user_id': telegram_user_id, 'telegram_username': (telegram_username or '')[:255]},
            )
    except IntegrityError:
        # The unique Telegram ID constraint also closes a simultaneous cross-account link race.
        return LinkResult(False, 409, 'This Telegram account is already linked to another account.')
    return LinkResult(True, 200, user=link_code.user)


def get_active_link(telegram_user_id: int):
    """Return (link, error) where error is None, 'not_linked' or 'inactive'."""
    link = TelegramLink.objects.select_related('user').filter(telegram_user_id=telegram_user_id).first()
    if link is None:
        return None, 'not_linked'
    if not link.user.is_active:
        return link, 'inactive'
    return link, None


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

def categories_for(user, category_type: Optional[str] = None):
    qs = Category.objects.filter(Q(is_default=True) | Q(user=user))
    if category_type:
        qs = qs.filter(category_type=category_type)
    return qs.order_by('category_type', 'name')


def resolve_category_by_name(user, transaction_type: str, category_name: str):
    """Name lookup used by the structured JSON endpoint (exact, then partial; own before default)."""
    name = (category_name or '').strip()
    if not name:
        return None
    own = Category.objects.filter(user=user, category_type=transaction_type)
    defaults = Category.objects.filter(is_default=True, category_type=transaction_type)
    return (
        own.filter(name__iexact=name).first()
        or defaults.filter(name__iexact=name).first()
        or own.filter(name__icontains=name).first()
        or defaults.filter(name__icontains=name).first()
    )


def fallback_category(user, transaction_type: str):
    name = FALLBACK_CATEGORY.get(transaction_type)
    if not name:
        return None
    return (
        Category.objects.filter(user=user, category_type=transaction_type, name__iexact=name).first()
        or Category.objects.filter(is_default=True, category_type=transaction_type, name__iexact=name).first()
    )


# ---------------------------------------------------------------------------
# Idempotent writes
# ---------------------------------------------------------------------------

def _run_idempotent(link, telegram_user_id: int, message_id: int, work):
    """
    Run `work()` (which returns a Transaction or None) at most once per
    (telegram_user_id, message_id). Returns (result, prior_message):
    prior_message is the existing TelegramMessage when this is a duplicate.
    """
    for attempt in range(5):
        try:
            with db_transaction.atomic():
                # Serialize requests for the same linked account on databases that support row locks.
                TelegramLink.objects.select_for_update().get(pk=link.pk)
                prior = TelegramMessage.objects.filter(
                    telegram_user_id=telegram_user_id, message_id=message_id
                ).select_related('transaction', 'transaction__category').first()
                if prior:
                    return None, prior
                result = work()
                TelegramMessage.objects.create(
                    telegram_user_id=telegram_user_id,
                    message_id=message_id,
                    transaction=result if isinstance(result, Transaction) else None,
                )
                return result, None
        except IntegrityError:
            # The unique key is the final guard on databases without effective row locks.
            prior = TelegramMessage.objects.filter(
                telegram_user_id=telegram_user_id, message_id=message_id
            ).select_related('transaction', 'transaction__category').first()
            if prior:
                return None, prior
            raise
        except OperationalError as exc:
            # SQLite has no row-level SELECT FOR UPDATE and can transiently lock on concurrent writes.
            if 'locked' not in str(exc).lower() or attempt == 4:
                raise
            time.sleep(0.02 * (attempt + 1))
    raise RuntimeError('unreachable')


def record_transaction(link, telegram_user_id: int, message_id: int, *, amount: Decimal,
                       transaction_type: str, category, txn_date: date, description: str):
    """Create a transaction once per Telegram message. Returns (transaction, prior_message)."""
    def work():
        return Transaction.objects.create(
            user=link.user, category=category, transaction_type=transaction_type,
            amount=amount, description=(description or '').strip(), date=txn_date,
        )
    return _run_idempotent(link, telegram_user_id, message_id, work)


def undo_last_transaction(link, telegram_user_id: int, message_id: int):
    """
    Delete the most recent transaction this Telegram user created through the bot.
    Returns (deleted_snapshot_dict_or_None, prior_message). The /undo message itself
    is recorded so a retried webhook cannot undo twice.
    """
    def work():
        last = (
            TelegramMessage.objects
            .filter(telegram_user_id=telegram_user_id, transaction__isnull=False, transaction__user=link.user)
            .select_related('transaction', 'transaction__category')
            .order_by('-processed_at', '-id')
            .first()
        )
        if not last:
            return {'deleted': None}
        txn = last.transaction
        snapshot = {
            'id': txn.pk,
            'amount': txn.amount,
            'transaction_type': txn.transaction_type,
            'category': txn.category.name if txn.category else None,
            'date': txn.date,
            'description': txn.description,
        }
        txn.delete()  # post_delete signal re-evaluates budget alerts
        return {'deleted': snapshot}

    result, prior = _run_idempotent(link, telegram_user_id, message_id, work)
    return (result or {}).get('deleted') if result else None, prior


# ---------------------------------------------------------------------------
# Read models for replies
# ---------------------------------------------------------------------------

def month_bounds(today: date, months_back: int = 0):
    year, month = today.year, today.month - months_back
    while month <= 0:
        month += 12
        year -= 1
    return year, month


def monthly_summary(user, year: int, month: int):
    qs = Transaction.objects.filter(user=user, date__year=year, date__month=month)
    income = qs.filter(transaction_type=Transaction.INCOME).aggregate(t=Sum('amount'))['t'] or Decimal(0)
    expense = qs.filter(transaction_type=Transaction.EXPENSE).aggregate(t=Sum('amount'))['t'] or Decimal(0)
    top = (
        qs.filter(transaction_type=Transaction.EXPENSE)
        .values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')[:3]
    )
    return {
        'year': year,
        'month': month,
        'income': income,
        'expense': expense,
        'net': income - expense,
        'count': qs.count(),
        'top_expenses': [
            {'category': row['category__name'] or 'Uncategorized', 'total': row['total']} for row in top
        ],
    }


def budget_status(user, year: int, month: int):
    rows = []
    for budget in Budget.objects.filter(user=user, year=year, month=month).select_related('category'):
        spent = Decimal(budget.get_spent_amount())
        limit = budget.monthly_limit
        pct = int(spent * 100 / limit) if limit else 0
        rows.append({
            'category': budget.category.name,
            'spent': spent,
            'limit': limit,
            'remaining': limit - spent,
            'percent': pct,
            'over': spent > limit,
        })
    return sorted(rows, key=lambda r: -r['percent'])


def budget_line_for(user, category, txn_date: date) -> str:
    """One-line budget status for the category of a just-logged expense ('' if no budget)."""
    if category is None:
        return ''
    budget = Budget.objects.filter(
        user=user, category=category, month=txn_date.month, year=txn_date.year
    ).first()
    if not budget:
        return ''
    spent = Decimal(budget.get_spent_amount())
    limit = budget.monthly_limit
    pct = int(spent * 100 / limit) if limit else 0
    if spent > limit:
        return f'⚠️ Over budget: {format_inr(spent)} of {format_inr(limit)} ({pct}%) for {category.name}.'
    if pct >= 80:
        return f'🟠 {pct}% of your {category.name} budget used ({format_inr(limit - spent)} left).'
    return f'🟢 {category.name} budget: {format_inr(spent)} of {format_inr(limit)} ({pct}%).'


def recent_transactions(user, limit: int = 5):
    return list(
        Transaction.objects.filter(user=user).select_related('category').order_by('-date', '-created_at')[:limit]
    )


def today() -> date:
    return timezone.localdate()
