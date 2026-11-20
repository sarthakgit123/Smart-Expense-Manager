"""Authenticated endpoints used by the n8n Telegram workflow."""
import hmac
import logging
import re
import time
from datetime import date as date_cls
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, OperationalError, transaction as db_transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Category, TelegramLink, TelegramLinkCode, TelegramMessage, Transaction

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
    code_value = code_value.strip().upper()
    username = request.data.get('telegram_username', '')
    if not isinstance(username, str):
        return Response({'ok': False, 'error': 'telegram_username must be a string'}, status=400)

    try:
        with db_transaction.atomic():
            try:
                link_code = TelegramLinkCode.objects.select_for_update().select_related('user').get(code=code_value)
            except TelegramLinkCode.DoesNotExist:
                return Response({'ok': False, 'error': 'Invalid or expired code'}, status=404)
            if not link_code.user.is_active:
                return Response({'ok': False, 'error': 'This account is inactive.'}, status=403)
            if not link_code.is_valid():
                return Response({'ok': False, 'error': 'Code has expired or already been used'}, status=400)

            # Never transfer a Telegram identity away from another Django account implicitly.
            if TelegramLink.objects.filter(telegram_user_id=telegram_user_id).exclude(user=link_code.user).exists():
                return Response({'ok': False, 'error': 'This Telegram account is already linked to another account.'}, status=409)

            link_code.used = True
            link_code.save(update_fields=['used'])
            TelegramLink.objects.update_or_create(
                user=link_code.user,
                defaults={'telegram_user_id': telegram_user_id, 'telegram_username': username[:255]},
            )
    except IntegrityError:
        # The unique Telegram ID constraint also closes a simultaneous cross-account link race.
        return Response({'ok': False, 'error': 'This Telegram account is already linked to another account.'}, status=409)

    return Response({
        'ok': True,
        'linked': True,
        'username': link_code.user.username,
        'first_name': link_code.user.first_name,
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

    try:
        link = TelegramLink.objects.select_related('user').get(telegram_user_id=telegram_user_id)
    except TelegramLink.DoesNotExist:
        return Response({'ok': False, 'error': 'Telegram account not linked. Send /link <code> first.'}, status=404)
    user = link.user
    if not user.is_active:
        return Response({'ok': False, 'error': 'This account is inactive.'}, status=403)

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

    category = None
    if category_name.strip():
        own_categories = Category.objects.filter(user=user, category_type=transaction_type)
        default_categories = Category.objects.filter(is_default=True, category_type=transaction_type)
        category = own_categories.filter(name__iexact=category_name.strip()).first()
        if not category:
            category = default_categories.filter(name__iexact=category_name.strip()).first()
        if not category:
            category = own_categories.filter(name__icontains=category_name.strip()).first()
        if not category:
            category = default_categories.filter(name__icontains=category_name.strip()).first()

    # The unique constraint and transaction protect retries, including concurrent n8n deliveries.
    for attempt in range(5):
        try:
            with db_transaction.atomic():
                # Serialize requests for the same linked account on databases that support row locks.
                TelegramLink.objects.select_for_update().get(pk=link.pk)
                prior = TelegramMessage.objects.filter(
                    telegram_user_id=telegram_user_id, message_id=message_id
                ).select_related('transaction').first()
                if prior:
                    return Response({'ok': True, 'duplicate': True, 'transaction_id': prior.transaction_id,
                                     'message': 'Duplicate Telegram message; transaction already processed.'})
                created = Transaction.objects.create(
                    user=user, category=category, transaction_type=transaction_type, amount=amount,
                    description=description.strip(), date=txn_date,
                )
                TelegramMessage.objects.create(
                    telegram_user_id=telegram_user_id, message_id=message_id, transaction=created,
                )
            break
        except IntegrityError:
            # The unique key is the final guard on databases without effective row locks.
            prior = TelegramMessage.objects.filter(
                telegram_user_id=telegram_user_id, message_id=message_id
            ).first()
            if prior:
                return Response({'ok': True, 'duplicate': True, 'transaction_id': prior.transaction_id,
                                 'message': 'Duplicate Telegram message; transaction already processed.'})
            raise
        except OperationalError as exc:
            # SQLite has no row-level SELECT FOR UPDATE and can transiently lock on concurrent writes.
            if 'locked' not in str(exc).lower() or attempt == 4:
                raise
            time.sleep(0.02 * (attempt + 1))

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
    try:
        user = TelegramLink.objects.select_related('user').get(telegram_user_id=telegram_user_id).user
    except TelegramLink.DoesNotExist:
        return Response({'ok': False, 'error': 'Telegram account not linked'}, status=404)
    if not user.is_active:
        return Response({'ok': False, 'error': 'This account is inactive.'}, status=403)
    qs = Category.objects.filter(Q(is_default=True) | Q(user=user))
    category_type = request.query_params.get('type', '').strip().upper()
    if category_type and category_type not in (Category.INCOME, Category.EXPENSE):
        return Response({'ok': False, 'error': 'type must be IN or EX'}, status=400)
    if category_type in (Category.INCOME, Category.EXPENSE):
        qs = qs.filter(category_type=category_type)
    return Response({'ok': True, 'categories': [
        {'id': item.pk, 'name': item.name, 'type': item.category_type, 'is_default': item.is_default}
        for item in qs.order_by('category_type', 'name')
    ]})
