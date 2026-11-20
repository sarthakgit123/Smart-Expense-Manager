"""
Tests for the Telegram bot integration.

Covers:
  1. TelegramLinkCode.generate_for_user — creates code and invalidates old ones
  2. TelegramLinkCode.is_valid — False when expired or used
  3. POST /api/telegram/link/ — confirm link: success, bad code, expired, wrong secret
  4. POST /api/telegram/expense/ — income, expense, duplicate message_id, unlinked,
     wrong secret, bad amount, bad type, category resolution
  5. GET  /api/telegram/categories/ — success, unlinked user, type filter
  6. Budget alert signal fires after Telegram transaction (integration test)
"""
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from transactions.models import (
    Budget,
    Category,
    TelegramLink,
    TelegramLinkCode,
    TelegramMessage,
    Transaction,
)

SECRET = 'test-n8n-secret-xyz'
N8N_SETTINGS = override_settings(N8N_WEBHOOK_SECRET=SECRET)


def _make_user(username='alice', email=None, password='pass1234!'):
    email = email or f'{username}@test.com'
    return User.objects.create_user(username=username, email=email, password=password)


def _expense_category(user=None):
    cat, _ = Category.objects.get_or_create(
        user=user,
        name='Food & Dining',
        category_type='EX',
        defaults={'is_default': user is None},
    )
    return cat


def _income_category(user=None):
    cat, _ = Category.objects.get_or_create(
        user=user,
        name='Salary',
        category_type='IN',
        defaults={'is_default': user is None},
    )
    return cat


# ===========================================================================
# 1 & 2 — Model unit tests
# ===========================================================================

class TelegramLinkCodeModelTests(TestCase):

    def setUp(self):
        self.user = _make_user()

    def test_generate_creates_code(self):
        code = TelegramLinkCode.generate_for_user(self.user, ttl_minutes=10)
        self.assertIsNotNone(code.pk)
        self.assertEqual(len(code.code), 16)
        self.assertFalse(code.used)

    def test_generate_invalidates_previous_unused_codes(self):
        old_code = TelegramLinkCode.generate_for_user(self.user, ttl_minutes=10)
        self.assertFalse(old_code.used)
        # Generate a second code — should invalidate the first
        new_code = TelegramLinkCode.generate_for_user(self.user, ttl_minutes=10)
        old_code.refresh_from_db()
        self.assertTrue(old_code.used)
        self.assertFalse(new_code.used)

    def test_is_valid_returns_true_for_fresh_code(self):
        code = TelegramLinkCode.generate_for_user(self.user, ttl_minutes=10)
        self.assertTrue(code.is_valid())

    def test_is_valid_returns_false_when_used(self):
        code = TelegramLinkCode.generate_for_user(self.user, ttl_minutes=10)
        code.used = True
        code.save()
        self.assertFalse(code.is_valid())

    def test_is_valid_returns_false_when_expired(self):
        code = TelegramLinkCode.generate_for_user(self.user, ttl_minutes=10)
        code.expires_at = timezone.now() - timedelta(seconds=1)
        code.save()
        self.assertFalse(code.is_valid())

    def test_zero_ttl_is_clamped_to_a_positive_minute(self):
        code = TelegramLinkCode.generate_for_user(self.user, ttl_minutes=0)
        self.assertTrue(code.is_valid())


# ===========================================================================
# 3 — POST /api/telegram/link/  (confirm_link)
# ===========================================================================

@N8N_SETTINGS
class ConfirmLinkTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('telegram-confirm-link')
        self.user = _make_user()
        self.link_code = TelegramLinkCode.generate_for_user(self.user, ttl_minutes=10)

    def _post(self, data, secret=SECRET):
        headers = {'HTTP_X_N8N_SECRET': secret}
        return self.client.post(self.url, data, format='json', **headers)

    def test_confirm_link_success(self):
        resp = self._post({
            'telegram_user_id': 123456789,
            'code': self.link_code.code,
            'telegram_username': 'alice_tg',
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertTrue(data['linked'])
        self.assertEqual(data['username'], self.user.username)
        # TelegramLink must exist
        tl = TelegramLink.objects.get(user=self.user)
        self.assertEqual(tl.telegram_user_id, 123456789)
        self.assertEqual(tl.telegram_username, 'alice_tg')
        # Code must be marked used
        self.link_code.refresh_from_db()
        self.assertTrue(self.link_code.used)

    def test_confirm_link_cannot_take_over_another_users_telegram_id(self):
        other_user = _make_user('bob')
        TelegramLink.objects.create(user=other_user, telegram_user_id=123456789)
        resp = self._post({'telegram_user_id': 123456789, 'code': self.link_code.code})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(TelegramLink.objects.get(telegram_user_id=123456789).user, other_user)
        self.link_code.refresh_from_db()
        self.assertFalse(self.link_code.used)

    def test_confirm_link_rejects_username_with_wrong_type(self):
        resp = self._post({
            'telegram_user_id': 99887766,
            'code': self.link_code.code,
            'telegram_username': ['not', 'a', 'string'],
        })
        self.assertEqual(resp.status_code, 400)

    def test_confirm_link_rejects_inactive_django_account(self):
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        resp = self._post({'telegram_user_id': 778899, 'code': self.link_code.code})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(TelegramLink.objects.filter(user=self.user).exists())

    def test_confirm_link_wrong_secret(self):
        resp = self._post({'telegram_user_id': 1, 'code': self.link_code.code}, secret='wrong')
        self.assertEqual(resp.status_code, 401)

    @override_settings(N8N_WEBHOOK_SECRET='')
    def test_confirm_link_rejects_requests_when_secret_is_not_configured(self):
        resp = self._post({'telegram_user_id': 1, 'code': self.link_code.code})
        self.assertEqual(resp.status_code, 401)

    def test_confirm_link_rejects_non_integer_telegram_id(self):
        resp = self._post({'telegram_user_id': 12.5, 'code': self.link_code.code})
        self.assertEqual(resp.status_code, 400)

    def test_confirm_link_bad_code(self):
        resp = self._post({'telegram_user_id': 999, 'code': 'DOESNOTEXIST'})
        self.assertEqual(resp.status_code, 404)

    def test_confirm_link_expired_code(self):
        self.link_code.expires_at = timezone.now() - timedelta(seconds=1)
        self.link_code.save()
        resp = self._post({'telegram_user_id': 999, 'code': self.link_code.code})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('expired', resp.json()['error'].lower())

    def test_confirm_link_already_used_code(self):
        self.link_code.used = True
        self.link_code.save()
        resp = self._post({'telegram_user_id': 999, 'code': self.link_code.code})
        self.assertEqual(resp.status_code, 400)

    def test_confirm_link_missing_fields(self):
        resp = self._post({'code': self.link_code.code})  # no telegram_user_id
        self.assertEqual(resp.status_code, 400)


# ===========================================================================
# 4 — POST /api/telegram/expense/  (create_telegram_transaction)
# ===========================================================================

@N8N_SETTINGS
class CreateTelegramTransactionTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('telegram-expense')
        self.user = _make_user()
        self.tg_id = 111222333
        TelegramLink.objects.create(
            user=self.user,
            telegram_user_id=self.tg_id,
            telegram_username='alice_tg',
        )
        # Seed default expense category
        self.expense_cat = _expense_category(user=None)
        self.expense_cat.is_default = True
        self.expense_cat.save()
        self.income_cat = _income_category(user=None)
        self.income_cat.is_default = True
        self.income_cat.save()

    def _post(self, data, secret=SECRET):
        return self.client.post(self.url, data, format='json', HTTP_X_N8N_SECRET=secret)

    def _base_expense(self, **kwargs):
        base = {
            'telegram_user_id': self.tg_id,
            'message_id': 1001,
            'amount': '250.00',
            'transaction_type': 'EX',
        }
        base.update(kwargs)
        return base

    def test_create_expense_success(self):
        resp = self._post(self._base_expense())
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['transaction_type'], 'Expense')
        self.assertEqual(Decimal(data['amount']), Decimal('250.00'))
        self.assertTrue(Transaction.objects.filter(user=self.user, transaction_type='EX').exists())

    def test_create_income_success(self):
        resp = self._post({
            'telegram_user_id': self.tg_id,
            'message_id': 1002,
            'amount': '5000',
            'transaction_type': 'IN',
            'category_name': 'Salary',
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data['transaction_type'], 'Income')
        self.assertEqual(data['category'], 'Salary')

    def test_duplicate_message_id_returns_cached(self):
        self._post(self._base_expense())  # first call
        resp = self._post(self._base_expense())  # exact same Telegram message_id
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get('duplicate'))

    def test_same_message_id_is_independent_for_a_different_telegram_user(self):
        second_user = _make_user('second_telegram_user')
        second_telegram_id = 987654321
        TelegramLink.objects.create(user=second_user, telegram_user_id=second_telegram_id)
        first = self._post(self._base_expense(message_id=777))
        second = self._post(self._base_expense(telegram_user_id=second_telegram_id, message_id=777))
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(Transaction.objects.filter(user__in=[self.user, second_user]).count(), 2)
        self.assertEqual(TelegramMessage.objects.filter(message_id=777).count(), 2)

    def test_unlinked_user_returns_404(self):
        resp = self._post(self._base_expense(telegram_user_id=99999999))
        self.assertEqual(resp.status_code, 404)

    def test_inactive_linked_user_cannot_create_transactions(self):
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        resp = self._post(self._base_expense())
        self.assertEqual(resp.status_code, 403)

    def test_wrong_secret_returns_401(self):
        resp = self._post(self._base_expense(), secret='bad-secret')
        self.assertEqual(resp.status_code, 401)

    def test_bad_amount_string_returns_400(self):
        resp = self._post(self._base_expense(amount='not-a-number', message_id=2001))
        self.assertEqual(resp.status_code, 400)

    def test_rejects_fractional_message_id_instead_of_truncating(self):
        resp = self._post(self._base_expense(message_id=12.5))
        self.assertEqual(resp.status_code, 400)

    def test_rejects_message_id_outside_database_bigint_range(self):
        resp = self._post(self._base_expense(message_id=2**63))
        self.assertEqual(resp.status_code, 400)

    def test_rejects_amount_with_more_than_two_decimal_places(self):
        resp = self._post(self._base_expense(amount='1.001', message_id=2004))
        self.assertEqual(resp.status_code, 400)

    def test_rejects_amount_beyond_model_precision(self):
        resp = self._post(self._base_expense(amount='10000000000', message_id=2005))
        self.assertEqual(resp.status_code, 400)

    def test_negative_amount_returns_400(self):
        resp = self._post(self._base_expense(amount='-100', message_id=2002))
        self.assertEqual(resp.status_code, 400)

    def test_bad_transaction_type_returns_400(self):
        resp = self._post(self._base_expense(transaction_type='SPEND', message_id=2003))
        self.assertEqual(resp.status_code, 400)

    def test_missing_message_id_returns_400(self):
        data = self._base_expense()
        del data['message_id']
        resp = self._post(data)
        self.assertEqual(resp.status_code, 400)

    def test_missing_amount_returns_400(self):
        data = self._base_expense()
        del data['amount']
        resp = self._post(data)
        self.assertEqual(resp.status_code, 400)

    def test_category_name_resolution_exact(self):
        resp = self._post(self._base_expense(message_id=3001, category_name='food & dining'))
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['category'], 'Food & Dining')

    def test_category_name_resolution_partial(self):
        resp = self._post(self._base_expense(message_id=3002, category_name='food'))
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['category'], 'Food & Dining')

    def test_unknown_category_name_still_succeeds_without_category(self):
        resp = self._post(self._base_expense(message_id=3003, category_name='zzzunknowncat'))
        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(resp.json()['category'])

    def test_explicit_date_stored_correctly(self):
        resp = self._post(self._base_expense(message_id=4001, date='2025-06-15'))
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['date'], '2025-06-15')

    def test_bad_date_format_returns_400(self):
        resp = self._post(self._base_expense(message_id=4002, date='15-06-2025'))
        self.assertEqual(resp.status_code, 400)

    def test_rejects_compact_date_even_though_python_accepts_it(self):
        resp = self._post(self._base_expense(message_id=4003, date='20250615'))
        self.assertEqual(resp.status_code, 400)

    def test_idempotency_record_created(self):
        self._post(self._base_expense(message_id=5001))
        self.assertTrue(TelegramMessage.objects.filter(message_id=5001, telegram_user_id=self.tg_id).exists())


# ===========================================================================
# 5 — GET /api/telegram/categories/
# ===========================================================================

@N8N_SETTINGS
class ListTelegramCategoriesTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('telegram-categories')
        self.user = _make_user()
        self.tg_id = 444555666
        TelegramLink.objects.create(
            user=self.user,
            telegram_user_id=self.tg_id,
            telegram_username='alice_tg',
        )
        # Default categories
        self.expense_cat = _expense_category(user=None)
        self.expense_cat.is_default = True
        self.expense_cat.save()
        self.income_cat = _income_category(user=None)
        self.income_cat.is_default = True
        self.income_cat.save()
        # User-specific category
        self.user_cat = Category.objects.create(
            user=self.user, name='Gaming', category_type='EX', is_default=False
        )

    def _get(self, params=None, secret=SECRET):
        params = params or {}
        return self.client.get(self.url, params, HTTP_X_N8N_SECRET=secret)

    def test_list_all_categories_success(self):
        resp = self._get({'telegram_user_id': self.tg_id})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        names = [c['name'] for c in data['categories']]
        self.assertIn('Food & Dining', names)
        self.assertIn('Salary', names)
        self.assertIn('Gaming', names)

    def test_unlinked_user_returns_404(self):
        resp = self._get({'telegram_user_id': 99999999})
        self.assertEqual(resp.status_code, 404)

    def test_wrong_secret_returns_401(self):
        resp = self._get({'telegram_user_id': self.tg_id}, secret='wrong')
        self.assertEqual(resp.status_code, 401)

    def test_type_filter_expense(self):
        resp = self._get({'telegram_user_id': self.tg_id, 'type': 'EX'})
        data = resp.json()
        for cat in data['categories']:
            self.assertEqual(cat['type'], 'EX')

    def test_type_filter_income(self):
        resp = self._get({'telegram_user_id': self.tg_id, 'type': 'IN'})
        data = resp.json()
        for cat in data['categories']:
            self.assertEqual(cat['type'], 'IN')

    def test_missing_telegram_user_id_returns_400(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 400)

    def test_inactive_linked_user_cannot_list_categories(self):
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        resp = self._get({'telegram_user_id': self.tg_id})
        self.assertEqual(resp.status_code, 403)

    def test_invalid_type_filter_returns_400(self):
        resp = self._get({'telegram_user_id': self.tg_id, 'type': 'expense'})
        self.assertEqual(resp.status_code, 400)


class ExistingAPIAndOAuthRegressionTests(TestCase):
    """The Telegram routes must not weaken existing DRF or OAuth behavior."""

    def setUp(self):
        self.owner = _make_user('api_owner')
        self.other = _make_user('api_other')

    def test_normal_transaction_api_still_requires_authentication(self):
        response = APIClient().get(reverse('transaction-list'))
        self.assertEqual(response.status_code, 403)

    def test_normal_transaction_api_keeps_user_data_isolated(self):
        own = Transaction.objects.create(
            user=self.owner, transaction_type='EX', amount=Decimal('10.00'), date=timezone.localdate()
        )
        Transaction.objects.create(
            user=self.other, transaction_type='EX', amount=Decimal('20.00'), date=timezone.localdate()
        )
        client = APIClient()
        client.force_authenticate(user=self.owner)
        response = client.get(reverse('transaction-list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['id'] for row in response.json()], [own.pk])

    def test_normal_transaction_api_still_creates_for_authenticated_user(self):
        client = APIClient()
        client.force_authenticate(user=self.owner)
        response = client.post(reverse('transaction-list'), {
            'transaction_type': 'IN',
            'amount': '125.00',
            'description': 'regular API transaction',
            'date': '2026-11-05',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Transaction.objects.filter(
            pk=response.json()['id'], user=self.owner, transaction_type='IN'
        ).exists())

    def test_normal_transaction_api_does_not_expose_another_users_detail(self):
        foreign = Transaction.objects.create(
            user=self.other, transaction_type='EX', amount=Decimal('20.00'), date=timezone.localdate()
        )
        client = APIClient()
        client.force_authenticate(user=self.owner)
        response = client.get(reverse('transaction-detail', args=[foreign.pk]))
        self.assertEqual(response.status_code, 404)

    def test_google_oauth_route_and_provider_configuration_remain_available(self):
        from django.conf import settings
        from django.urls import resolve

        self.assertEqual(resolve('/auth/google/login/').url_name, 'google_login')
        self.assertIn('google', settings.SOCIALACCOUNT_PROVIDERS)


class TelegramLinkPageTests(TestCase):
    def test_link_page_requires_login(self):
        response = self.client.get(reverse('accounts:telegram-link'))
        self.assertEqual(response.status_code, 302)

    def test_link_code_page_post_requires_csrf_and_authenticated_session(self):
        client = Client(enforce_csrf_checks=True)
        user = _make_user('telegram_page_user')
        client.force_login(user)
        page_url = reverse('accounts:telegram-link')
        self.assertEqual(client.get(page_url).status_code, 200)
        self.assertEqual(client.post(page_url).status_code, 403)

        token = client.cookies['csrftoken'].value
        response = client.post(page_url, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)
        code = TelegramLinkCode.objects.get(user=user)
        self.assertContains(response, code.code)

    @override_settings(TELEGRAM_BOT_USERNAME='SmartExpenseTestBot')
    def test_link_page_shows_bot_deep_link_when_configured(self):
        user = _make_user('tg_botlink_user')
        self.client.force_login(user)
        response = self.client.get(reverse('accounts:telegram-link'))
        self.assertContains(response, 'https://t.me/SmartExpenseTestBot')

    @override_settings(TELEGRAM_BOT_USERNAME='')
    def test_link_page_has_no_bot_link_when_not_configured(self):
        user = _make_user('tg_nobot_user')
        self.client.force_login(user)
        response = self.client.get(reverse('accounts:telegram-link'))
        self.assertNotContains(response, 'https://t.me/')

    def test_navbar_links_to_telegram_page(self):
        user = _make_user('tg_nav_user')
        self.client.force_login(user)
        response = self.client.get(reverse('accounts:dashboard'))
        self.assertContains(response, reverse('accounts:telegram-link'))


class TelegramUnlinkTests(TestCase):
    def setUp(self):
        self.user = _make_user('tg_unlink_user')
        self.client.force_login(self.user)
        self.url = reverse('accounts:telegram-unlink')

    def test_unlink_requires_login(self):
        self.client.logout()
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response['Location'])

    def test_unlink_rejects_get(self):
        TelegramLink.objects.create(user=self.user, telegram_user_id=111222333)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertTrue(TelegramLink.objects.filter(user=self.user).exists())

    def test_unlink_requires_csrf(self):
        TelegramLink.objects.create(user=self.user, telegram_user_id=111222334)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url).status_code, 403)
        self.assertTrue(TelegramLink.objects.filter(user=self.user).exists())

    def test_unlink_removes_link_and_voids_open_codes(self):
        TelegramLink.objects.create(user=self.user, telegram_user_id=111222335)
        code = TelegramLinkCode.generate_for_user(self.user)
        response = self.client.post(self.url)
        self.assertRedirects(response, reverse('accounts:telegram-link'))
        self.assertFalse(TelegramLink.objects.filter(user=self.user).exists())
        code.refresh_from_db()
        self.assertTrue(code.used)

    def test_unlink_only_affects_current_user(self):
        other = _make_user('tg_unlink_other')
        TelegramLink.objects.create(user=other, telegram_user_id=999888777)
        self.client.post(self.url)
        self.assertTrue(TelegramLink.objects.filter(user=other).exists())

    @N8N_SETTINGS
    def test_unlinked_telegram_user_can_no_longer_add_transactions(self):
        TelegramLink.objects.create(user=self.user, telegram_user_id=111222336)
        self.client.post(self.url)
        response = APIClient().post(
            reverse('telegram-expense'),
            {'telegram_user_id': 111222336, 'message_id': 1, 'amount': '10', 'transaction_type': 'EX'},
            format='json',
            HTTP_X_N8N_SECRET=SECRET,
        )
        self.assertEqual(response.status_code, 404)


class TelegramTimezoneTests(TestCase):
    @N8N_SETTINGS
    def test_default_date_uses_ist_local_date(self):
        """At 20:00 UTC it is already the next day in IST; the transaction date must follow IST."""
        from datetime import datetime, timezone as dt_timezone
        user = _make_user('tg_tz_user')
        TelegramLink.objects.create(user=user, telegram_user_id=444555666)
        fake_now = datetime(2026, 3, 31, 20, 0, tzinfo=dt_timezone.utc)  # 01:30 IST on 1 April
        with patch('django.utils.timezone.now', return_value=fake_now):
            response = APIClient().post(
                reverse('telegram-expense'),
                {'telegram_user_id': 444555666, 'message_id': 5, 'amount': '10', 'transaction_type': 'EX'},
                format='json',
                HTTP_X_N8N_SECRET=SECRET,
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['date'], '2026-04-01')


@N8N_SETTINGS
class ConcurrentTelegramDuplicateTests(TransactionTestCase):
    """Concurrent retries must produce one transaction and idempotency record."""

    reset_sequences = True

    def setUp(self):
        self.user = _make_user('concurrent_user')
        self.telegram_user_id = 777666555
        TelegramLink.objects.create(user=self.user, telegram_user_id=self.telegram_user_id)
        self.url = reverse('telegram-expense')

    def _submit(self):
        close_old_connections()
        try:
            return APIClient().post(
                self.url,
                {
                    'telegram_user_id': self.telegram_user_id,
                    'message_id': 321,
                    'amount': '15.00',
                    'transaction_type': 'EX',
                },
                format='json',
                HTTP_X_N8N_SECRET=SECRET,
            ).status_code
        finally:
            close_old_connections()

    def test_simultaneous_retries_create_only_one_transaction(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _index: self._submit(), range(2)))

        self.assertCountEqual(statuses, [200, 201])
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 1)
        self.assertEqual(TelegramMessage.objects.filter(
            telegram_user_id=self.telegram_user_id, message_id=321
        ).count(), 1)


# ===========================================================================
# 6 — Integration test: budget alert signal fires after Telegram transaction
# ===========================================================================

@N8N_SETTINGS
class BudgetAlertAfterTelegramTransactionTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('telegram-expense')
        self.user = _make_user('budget_user')
        self.tg_id = 777888999
        TelegramLink.objects.create(
            user=self.user,
            telegram_user_id=self.tg_id,
            telegram_username='budget_tg',
        )
        # Seed expense category
        self.cat = Category.objects.create(
            user=self.user, name='Groceries', category_type='EX', is_default=False
        )
        # Create a budget that will be exceeded
        from django.utils import timezone as tz
        today = tz.now().date()
        self.budget = Budget.objects.create(
            user=self.user,
            category=self.cat,
            monthly_limit=Decimal('100.00'),
            month=today.month,
            year=today.year,
        )

    @patch('accounts.utils.send_budget_alert')
    def test_budget_alert_triggered_after_telegram_expense(self, mock_alert):
        """Creating an over-budget transaction via Telegram should fire the alert."""
        resp = self.client.post(
            self.url,
            {
                'telegram_user_id': self.tg_id,
                'message_id': 9001,
                'amount': '150.00',  # exceeds 100 budget
                'transaction_type': 'EX',
                'category_name': 'Groceries',
            },
            format='json',
            HTTP_X_N8N_SECRET=SECRET,
        )
        self.assertEqual(resp.status_code, 201)
        # The post_save signal should have called check_and_trigger_budget_alerts,
        # which calls send_budget_alert when over budget.
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 1)
        created = Transaction.objects.get(user=self.user)
        self.assertEqual(created.category_id, self.cat.pk, f'txn date={created.date}, budget={self.budget.month}/{self.budget.year}')
        self.assertEqual(Budget.objects.get(pk=self.budget.pk).get_spent_amount(), Decimal('150.00'))
        mock_alert.assert_called_once()
