"""Authenticated endpoints used by the n8n Telegram workflow."""
import calendar
import hmac
import logging
import re
from datetime import date as date_cls
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import telegram_service as svc
from .models import Category, TelegramLinkCode, Transaction
from .telegram_parser import ParseError, format_inr, parse_transaction_text

logger = logging.getLogger(__name__)


def _check_n8n_secret(request):
    configured = getattr(settings, 'N8N_WEBHOOK_SECRET', '')
    supplied = request.headers.get('X-N8N-Secret', '')
    return bool(configured) and hmac.compare_digest(configured, supplied)


def _auth_error():
    return Response({'ok': False, 'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)


def _positive_int(value, field_name):
    if isinstance(value, bool) or not (
        isinstance(value, int) or (isinstance(value, str) and re.fullmatch(r'\d+', value))
    ):
        raise ValueError(f'{field_name} must be a positive integer')
    parsed = int(value)
    if not 0 < parsed <= 9223372036854775807:
        raise ValueError(f'{field_name} must be a positive 64-bit integer')
    return parsed


# ---------------------------------------------------------------------------
# Web session endpoint
# ---------------------------------------------------------------------------

@api_view(['POST'])
@authentication_classes([])
@permission_classes([])
def generate_link_code(request):
    """Create a code from the logged-in web session (CSRF checked by SessionAuthentication)."""
    from rest_framework.authentication import SessionAuthentication

    try:
        authenticated = SessionAuthentication().authenticate(request)
    except Exception:
        authenticated = None
    if not authenticated:
        return Response({'ok': False, 'error': 'Login required'}, status=401)

    ttl = max(1, int(getattr(settings, 'TELEGRAM_LINK_CODE_TTL_MINUTES', 10)))
    code = TelegramLinkCode.generate_for_user(authenticated[0], ttl_minutes=ttl)
    return Response({
        'ok': True,
        'code': code.code,
        'expires_at': code.expires_at.isoformat(),
        'instructions': f'Send /link {code.code} to the bot within {ttl} minutes.',
    })


# ---------------------------------------------------------------------------
# Structured n8n endpoints (n8n does the parsing)
# ---------------------------------------------------------------------------

@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def confirm_link(request):
    if not _check_n8n_secret(request):
        return _auth_error()
    try:
        telegram_user_id = _positive_int(request.data.get('telegram_user_id'), 'telegram_user_id')
    except ValueError as exc:
        return Response({'ok': False, 'error': str(exc)}, status=400)
    code_value = request.data.get('code', '')
    if not isinstance(code_value, str) or not code_value.strip():
        return Response({'ok': False, 'error': 'code is required'}, status=400)
    username = request.data.get('telegram_username', '')
    if not isinstance(username, str):
        return Response({'ok': False, 'error': 'telegram_username must be a string'}, status=400)

    result = svc.link_account(telegram_user_id, username, code_value)
    if not result.ok:
        return Response({'ok': False, 'error': result.error}, status=result.status)
    return Response({
        'ok': True,
        'linked': True,
        'username': result.user.username,
        'first_name': result.user.first_name,
        'message': 'Account linked. You can now log transactions via this bot.',
    })


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def create_telegram_transaction(request):
    """Create an income or expense; message_id is Telegram's message.message_id."""
    if not _check_n8n_secret(request):
        return _auth_error()
    try:
        telegram_user_id = _positive_int(request.data.get('telegram_user_id'), 'telegram_user_id')
        message_id = _positive_int(request.data.get('message_id'), 'message_id')
    except ValueError as exc:
        return Response({'ok': False, 'error': str(exc)}, status=400)

    link, link_error = svc.get_active_link(telegram_user_id)
    if link_error == 'not_linked':
        return Response({'ok': False, 'error': 'Telegram account not linked. Send /link <code> first.'}, status=404)
    if link_error == 'inactive':
        return Response({'ok': False, 'error': 'This account is inactive.'}, status=403)
    user = link.user

    try:
        amount = Decimal(str(request.data.get('amount', '')))
        if not amount.is_finite() or amount <= 0 or amount > Decimal('9999999999.99'):
            raise ValueError
    except (InvalidOperation, ValueError, TypeError):
        return Response({'ok': False, 'error': 'amount must be a positive number with at most 2 decimal places'}, status=400)
    if amount.as_tuple().exponent < -2:
        return Response({'ok': False, 'error': 'amount supports at most 2 decimal places'}, status=400)

    transaction_type = str(request.data.get('transaction_type', '')).strip().upper()
    if transaction_type not in (Transaction.INCOME, Transaction.EXPENSE):
        return Response({'ok': False, 'error': 'transaction_type must be IN or EX'}, status=400)
    raw_date = request.data.get('date')
    try:
        if raw_date and (not isinstance(raw_date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw_date)):
            raise ValueError
        txn_date = date_cls.fromisoformat(raw_date) if raw_date else timezone.localdate()
    except (TypeError, ValueError):
        return Response({'ok': False, 'error': 'date must be YYYY-MM-DD'}, status=400)
    description = request.data.get('description', '')
    category_name = request.data.get('category_name', '')
    if not isinstance(description, str) or not isinstance(category_name, str):
        return Response({'ok': False, 'error': 'description and category_name must be strings'}, status=400)

    category = svc.resolve_category_by_name(user, transaction_type, category_name)
    created, prior = svc.record_transaction(
        link, telegram_user_id, message_id,
        amount=amount, transaction_type=transaction_type, category=category,
        txn_date=txn_date, description=description,
    )
    if prior:
        return Response({'ok': True, 'duplicate': True, 'transaction_id': prior.transaction_id,
                         'message': 'Duplicate Telegram message; transaction already processed.'})

    return Response({
        'ok': True,
        'transaction_id': created.pk,
        'amount': str(created.amount),
        'transaction_type': created.get_transaction_type_display(),
        'category': created.category.name if created.category else None,
        'date': str(created.date),
        'description': created.description,
        'message': f"{'Expense' if transaction_type == Transaction.EXPENSE else 'Income'} of {created.amount} logged!",
    }, status=201)


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def list_telegram_categories(request):
    if not _check_n8n_secret(request):
        return _auth_error()
    try:
        telegram_user_id = _positive_int(request.query_params.get('telegram_user_id'), 'telegram_user_id')
    except ValueError as exc:
        return Response({'ok': False, 'error': str(exc)}, status=400)
    link, link_error = svc.get_active_link(telegram_user_id)
    if link_error == 'not_linked':
        return Response({'ok': False, 'error': 'Telegram account not linked'}, status=404)
    if link_error == 'inactive':
        return Response({'ok': False, 'error': 'This account is inactive.'}, status=403)
    category_type = request.query_params.get('type', '').strip().upper()
    if category_type and category_type not in (Category.INCOME, Category.EXPENSE):
        return Response({'ok': False, 'error': 'type must be IN or EX'}, status=400)
    qs = svc.categories_for(link.user, category_type or None)
    return Response({'ok': True, 'categories': [
        {'id': item.pk, 'name': item.name, 'type': item.category_type, 'is_default': item.is_default}
        for item in qs
    ]})


# ---------------------------------------------------------------------------
# Chat endpoint: n8n forwards the raw Telegram message, Django does the rest
# ---------------------------------------------------------------------------

HELP_TEXT = (
    "💸 Smart Expense Manager bot\n"
    "\n"
    "Log a transaction by just typing it:\n"
    "• 250 groceries\n"
    "• spent 1,200 on petrol yesterday\n"
    "• +5000 salary   (or: received 5000 salary)\n"
    "• 2.5k rent 01/11\n"
    "\n"
    "Commands:\n"
    "/summary – this month's income & expenses (/summary last for last month)\n"
    "/budget – how much of each budget you've used\n"
    "/recent – your last 5 transactions\n"
    "/categories – categories you can use\n"
    "/undo – delete the last transaction you added here\n"
    "/help – show this message"
)

NOT_LINKED_TEXT = (
    "👋 This Telegram account isn't linked yet.\n"
    "\n"
    "1. Log in to Smart Expense Manager on the web\n"
    "2. Open the Telegram page and tap Generate Link Code\n"
    "3. Send /link YOUR_CODE here (or tap the Open in Telegram button)"
)

INACTIVE_TEXT = '⛔ Your Smart Expense Manager account is inactive.'

_COMMAND_RE = re.compile(r'^/([A-Za-z_]+)(?:@\w+)?(?:\s+(.*))?$', re.S)


def _reply(action, text, ok=True, **extra):
    return Response({'ok': ok, 'action': action, 'reply_text': text, **extra}, status=200)


def _txn_line(txn) -> str:
    sign = '+' if txn.transaction_type == Transaction.INCOME else '-'
    category = txn.category.name if txn.category else 'Uncategorized'
    desc = f' · {txn.description}' if txn.description else ''
    return f'{txn.date:%d %b} {sign}{format_inr(txn.amount)} {category}{desc}'


def _handle_link(telegram_user_id, username, code):
    if not code:
        return _reply('link_error', 'Send /link followed by the code from the website, e.g. /link 1A2B3C4D5E6F7A8B', ok=False)
    result = svc.link_account(telegram_user_id, username, code)
    if not result.ok:
        messages = {
            404: '❌ That code is not valid. Generate a new one on the website.',
            400: '⌛ That code has expired or was already used. Generate a new one on the website.',
            403: INACTIVE_TEXT,
            409: '⚠️ This Telegram account is already linked to a different Smart Expense Manager account. Unlink it there first.',
        }
        return _reply('link_error', messages.get(result.status, '❌ Could not link your account.'), ok=False)
    name = result.user.first_name or result.user.username
    return _reply('linked', f'✅ Linked to {name}\'s account!\n\n{HELP_TEXT}', username=result.user.username)


def _handle_summary(user, arg):
    months_back = 1 if (arg or '').strip().lower() in ('last', 'prev', 'previous') else 0
    year, month = svc.month_bounds(svc.today(), months_back)
    data = svc.monthly_summary(user, year, month)
    lines = [
        f'📊 {calendar.month_name[month]} {year}',
        f'Income:   {format_inr(data["income"])}',
        f'Expenses: {format_inr(data["expense"])}',
        f'Net:      {format_inr(data["net"])}',
        f'Transactions: {data["count"]}',
    ]
    if data['top_expenses']:
        lines.append('')
        lines.append('Top spending:')
        lines += [f'• {row["category"]}: {format_inr(row["total"])}' for row in data['top_expenses']]
    summary = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in data.items() if k != 'top_expenses'}
    return _reply('summary', '\n'.join(lines), summary=summary)


def _handle_budget(user):
    today = svc.today()
    rows = svc.budget_status(user, today.year, today.month)
    if not rows:
        return _reply('budget', f'No budgets set for {calendar.month_name[today.month]}. Add one on the website.')
    lines = [f'💰 Budgets – {calendar.month_name[today.month]} {today.year}']
    for r in rows:
        icon = '🔴' if r['over'] else ('🟠' if r['percent'] >= 80 else '🟢')
        lines.append(f'{icon} {r["category"]}: {format_inr(r["spent"])} / {format_inr(r["limit"])} ({r["percent"]}%)')
    return _reply('budget', '\n'.join(lines))


def _handle_recent(user):
    txns = svc.recent_transactions(user, 5)
    if not txns:
        return _reply('recent', 'No transactions yet. Try sending "250 groceries".')
    return _reply('recent', '🧾 Recent transactions\n' + '\n'.join(_txn_line(t) for t in txns))


def _handle_categories(user, arg):
    arg = (arg or '').strip().upper()
    cat_type = arg if arg in (Category.INCOME, Category.EXPENSE) else None
    cats = list(svc.categories_for(user, cat_type))
    expense = [c.name for c in cats if c.category_type == Category.EXPENSE]
    income = [c.name for c in cats if c.category_type == Category.INCOME]
    parts = []
    if expense:
        parts.append('🔻 Expense: ' + ', '.join(expense))
    if income:
        parts.append('🔺 Income: ' + ', '.join(income))
    return _reply('categories', '\n\n'.join(parts) or 'No categories found.')


def _handle_undo(link, telegram_user_id, message_id):
    deleted, prior = svc.undo_last_transaction(link, telegram_user_id, message_id)
    if prior:
        return _reply('duplicate', 'This /undo was already processed.')
    if not deleted:
        return _reply('undo', 'Nothing to undo – no transactions were added from Telegram yet.', ok=False)
    sign = '+' if deleted['transaction_type'] == Transaction.INCOME else '-'
    category = deleted['category'] or 'Uncategorized'
    return _reply(
        'undo',
        f'↩️ Deleted: {deleted["date"]:%d %b} {sign}{format_inr(deleted["amount"])} {category}',
        transaction_id=deleted['id'],
    )


def _handle_free_text(link, telegram_user_id, message_id, text):
    user = link.user
    categories = list(svc.categories_for(user))
    try:
        parsed = parse_transaction_text(text, categories, svc.today())
    except ParseError as exc:
        return _reply('parse_error', f'🤔 {exc}\n\nSend /help for examples.', ok=False)

    category = parsed.category or svc.fallback_category(user, parsed.transaction_type)
    created, prior = svc.record_transaction(
        link, telegram_user_id, message_id,
        amount=parsed.amount, transaction_type=parsed.transaction_type, category=category,
        txn_date=parsed.date, description=parsed.description,
    )
    if prior:
        txn = prior.transaction
        text_out = f'Already logged: {_txn_line(txn)}' if txn else 'This message was already processed.'
        return _reply('duplicate', text_out, duplicate=True, transaction_id=prior.transaction_id)

    kind = 'Income' if created.transaction_type == Transaction.INCOME else 'Expense'
    category_name = created.category.name if created.category else 'Uncategorized'
    lines = [f'✅ {kind} of {format_inr(created.amount)} logged']
    lines.append(f'🏷️ {category_name} · 📅 {created.date:%d %b %Y}')
    if created.description:
        lines.append(f'📝 {created.description}')
    if created.transaction_type == Transaction.EXPENSE:
        budget_line = svc.budget_line_for(user, created.category, created.date)
        if budget_line:
            lines.append(budget_line)
    lines.append('Wrong? Send /undo')
    return _reply(
        'transaction_created',
        '\n'.join(lines),
        transaction={
            'id': created.pk,
            'amount': str(created.amount),
            'transaction_type': created.transaction_type,
            'category': created.category.name if created.category else None,
            'date': str(created.date),
            'description': created.description,
        },
    )


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def telegram_message(request):
    """
    Single entry point for n8n: forward every Telegram text message here.

    Body: telegram_user_id (message.from.id), message_id (message.message_id),
          text (message.text), telegram_username (optional, message.from.username).

    Every user-facing outcome returns HTTP 200 with
        {"ok": bool, "action": "...", "reply_text": "..."}
    so the workflow can always send reply_text back to the chat. 4xx is only
    used for integration errors (bad secret, malformed IDs).
    """
    if not _check_n8n_secret(request):
        return _auth_error()
    try:
        telegram_user_id = _positive_int(request.data.get('telegram_user_id'), 'telegram_user_id')
        message_id = _positive_int(request.data.get('message_id'), 'message_id')
    except ValueError as exc:
        return Response({'ok': False, 'error': str(exc)}, status=400)
    text = request.data.get('text', '')
    username = request.data.get('telegram_username', '') or ''
    if not isinstance(text, str) or not isinstance(username, str):
        return Response({'ok': False, 'error': 'text and telegram_username must be strings'}, status=400)
    text = text.strip()

    command, arg = None, ''
    match = _COMMAND_RE.match(text)
    if match:
        command, arg = match.group(1).lower(), (match.group(2) or '').strip()

    # Commands that work before linking.
    if command == 'link':
        return _handle_link(telegram_user_id, username, arg)
    if command == 'start' and arg:
        # Deep link from the website: t.me/<bot>?start=<CODE>
        return _handle_link(telegram_user_id, username, arg)

    link, link_error = svc.get_active_link(telegram_user_id)
    if link_error == 'not_linked':
        return _reply('not_linked', NOT_LINKED_TEXT, ok=False)
    if link_error == 'inactive':
        return _reply('inactive', INACTIVE_TEXT, ok=False)

    if command in ('start', 'help'):
        return _reply('help', HELP_TEXT)
    if command == 'summary':
        return _handle_summary(link.user, arg)
    if command in ('budget', 'budgets'):
        return _handle_budget(link.user)
    if command in ('recent', 'last'):
        return _handle_recent(link.user)
    if command == 'categories':
        return _handle_categories(link.user, arg)
    if command == 'undo':
        return _handle_undo(link, telegram_user_id, message_id)
    if command:
        return _reply('unknown_command', f'Unknown command /{command}. Send /help to see what I can do.', ok=False)

    if not text:
        return _reply('parse_error', 'I can only read text messages. Send /help for examples.', ok=False)
    return _handle_free_text(link, telegram_user_id, message_id, text)
