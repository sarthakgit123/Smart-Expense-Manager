"""
Phase 2 tests: free-text parser and the POST /api/telegram/message/ chat endpoint.
"""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from transactions.models import (
    DEFAULT_CATEGORIES,
    Budget,
    Category,
    TelegramLink,
    TelegramLinkCode,
    TelegramMessage,
    Transaction,
)
from transactions.telegram_parser import (
    ParseError,
    format_inr,
    match_category,
    parse_amount_token,
    parse_transaction_text,
)

SECRET = 'phase2-test-secret'
TODAY = date(2026, 11, 20)


def _cats():
    """Lightweight stand-ins for the 18 global default categories."""
    return [SimpleNamespace(name=n, category_type=t, user_id=None) for n, t in DEFAULT_CATEGORIES]


# ===========================================================================
# Parser (no database)
# ===========================================================================

class AmountParsingTests(SimpleTestCase):
    def test_plain_and_formatted_amounts(self):
        cases = {
            '250': '250.00', '1,250': '1250.00', '1,25,000': '125000.00', '99.5': '99.50',
            '₹300': '300.00', 'rs.450': '450.00', 'Rs450': '450.00', '500rs': '500.00',
            '200/-': '200.00', '2k': '2000.00', '2.5k': '2500.00', '1.25K': '1250.00',
        }
        for token, expected in cases.items():
            with self.subTest(token=token):
                self.assertEqual(parse_amount_token(token), Decimal(expected))

    def test_non_amount_tokens_return_none(self):
        for token in ('groceries', 'k', 'abc123', ''):
            with self.subTest(token=token):
                self.assertIsNone(parse_amount_token(token))

    def test_invalid_amounts_raise(self):
        for token in ('0', '1.234', '99999999999'):
            with self.subTest(token=token), self.assertRaises(ParseError):
                parse_amount_token(token)


class TransactionTextParsingTests(SimpleTestCase):
    def parse(self, text):
        return parse_transaction_text(text, _cats(), TODAY)

    def test_simple_expense_defaults_to_today(self):
        p = self.parse('250 groceries')
        self.assertEqual((p.amount, p.transaction_type, p.category.name, p.date),
                         (Decimal('250.00'), 'EX', 'Groceries', TODAY))
        self.assertEqual(p.description, 'groceries')

    def test_spent_on_yesterday(self):
        p = self.parse('spent 1,200 on petrol yesterday')
        self.assertEqual(p.amount, Decimal('1200.00'))
        self.assertEqual(p.transaction_type, 'EX')
        self.assertEqual(p.category.name, 'Transportation & Fuel')
        self.assertEqual(p.date, TODAY - timedelta(days=1))
        self.assertEqual(p.description, 'petrol')

    def test_plus_sign_means_income(self):
        p = self.parse('+5000 salary')
        self.assertEqual((p.transaction_type, p.category.name), ('IN', 'Salary'))

    def test_income_word(self):
        p = self.parse('received 2.5k freelance 18/11')
        self.assertEqual(p.amount, Decimal('2500.00'))
        self.assertEqual(p.transaction_type, 'IN')
        self.assertEqual(p.category.name, 'Freelance & Consulting')
        self.assertEqual(p.date, date(2026, 11, 18))

    def test_income_category_without_keyword_infers_income(self):
        p = self.parse('45000 salary november')
        self.assertEqual(p.transaction_type, 'IN')
        self.assertFalse(p.explicit_type)

    def test_alias_matching(self):
        self.assertEqual(self.parse('350 swiggy dinner').category.name, 'Food & Dining')
        self.assertEqual(self.parse('199 netflix').category.name, 'Entertainment & Leisure')
        self.assertEqual(self.parse('12000 rent').category.name, 'Housing & Rent')

    def test_word_of_category_name(self):
        self.assertEqual(self.parse('120 food').category.name, 'Food & Dining')

    def test_amount_after_text(self):
        p = self.parse('groceries 480')
        self.assertEqual((p.amount, p.category.name), (Decimal('480.00'), 'Groceries'))

    def test_iso_date_and_currency_word(self):
        p = self.parse('rs 99 netflix 2026-11-02')
        self.assertEqual((p.amount, p.date), (Decimal('99.00'), date(2026, 11, 2)))

    def test_ddmm_in_future_rolls_back_to_last_year(self):
        p = self.parse('500 gift 28/12')
        self.assertEqual(p.date, date(2025, 12, 28))

    def test_unknown_category_has_no_match(self):
        p = self.parse('75 random stuff')
        self.assertIsNone(p.category)
        self.assertEqual(p.transaction_type, 'EX')
        self.assertEqual(p.description, 'random stuff')

    def test_errors(self):
        for text in ('', 'hello there', '250 food 2026-12-25', '250 food 31/02/2026', 'x' * 501):
            with self.subTest(text=text[:30]), self.assertRaises(ParseError):
                self.parse(text)

    def test_explicit_income_restricts_category_search(self):
        p = self.parse('income 300 investments')
        self.assertEqual(p.category.name, 'Investments & Dividends')

    def test_user_category_preferred_over_default(self):
        own = SimpleNamespace(name='Groceries', category_type='EX', user_id=7)
        cats = _cats() + [own]
        self.assertIs(match_category(['groceries'], cats), own)


class FormatInrTests(SimpleTestCase):
    def test_indian_grouping(self):
        self.assertEqual(format_inr(Decimal('250')), '₹250')
        self.assertEqual(format_inr(Decimal('1250.5')), '₹1,250.50')
        self.assertEqual(format_inr(Decimal('1250000')), '₹12,50,000')
        self.assertEqual(format_inr(Decimal('-4500')), '-₹4,500')


# ===========================================================================
# Endpoint
# ===========================================================================

@override_settings(N8N_WEBHOOK_SECRET=SECRET)
class TelegramMessageEndpointTests(TestCase):
    TG_ID = 5550001

    def setUp(self):
        Category.ensure_default_categories()
        self.user = User.objects.create_user('bot_user', 'bot@test.com', 'pass1234!', first_name='Asha')
        self.link = TelegramLink.objects.create(user=self.user, telegram_user_id=self.TG_ID, telegram_username='asha')
        self.api = APIClient()
        self.url = reverse('telegram-message')
        self._msg = 100

    def send(self, text, tg_id=None, message_id=None, secret=SECRET):
        if message_id is None:
            self._msg += 1
            message_id = self._msg
        return self.api.post(
            self.url,
            {'telegram_user_id': tg_id or self.TG_ID, 'message_id': message_id, 'text': text, 'telegram_username': 'asha'},
            format='json',
            HTTP_X_N8N_SECRET=secret,
        )

    # --- auth / protocol -------------------------------------------------
    def test_wrong_secret_is_401(self):
        self.assertEqual(self.send('250 food', secret='nope').status_code, 401)

    def test_bad_ids_are_400(self):
        r = self.api.post(self.url, {'telegram_user_id': 'abc', 'message_id': 1, 'text': 'hi'},
                          format='json', HTTP_X_N8N_SECRET=SECRET)
        self.assertEqual(r.status_code, 400)

    # --- free text -------------------------------------------------------
    def test_free_text_creates_expense_with_reply(self):
        r = self.send('250 groceries')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['ok'])
        self.assertEqual(r.data['action'], 'transaction_created')
        self.assertIn('₹250', r.data['reply_text'])
        self.assertIn('Groceries', r.data['reply_text'])
        txn = Transaction.objects.get(user=self.user)
        self.assertEqual((txn.amount, txn.transaction_type, txn.category.name),
                         (Decimal('250.00'), 'EX', 'Groceries'))
        self.assertTrue(TelegramMessage.objects.filter(transaction=txn).exists())

    def test_free_text_income(self):
        r = self.send('+45000 salary')
        self.assertEqual(r.data['transaction']['transaction_type'], 'IN')
        self.assertIn('Income', r.data['reply_text'])

    def test_unknown_category_falls_back_to_miscellaneous(self):
        r = self.send('75 random stuff')
        self.assertEqual(r.data['transaction']['category'], 'Miscellaneous')

    def test_parse_error_returns_200_with_hint(self):
        r = self.send('hello bot')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['ok'])
        self.assertEqual(r.data['action'], 'parse_error')
        self.assertFalse(Transaction.objects.exists())

    def test_duplicate_message_is_not_logged_twice(self):
        first = self.send('250 groceries', message_id=777)
        second = self.send('250 groceries', message_id=777)
        self.assertEqual(first.data['action'], 'transaction_created')
        self.assertEqual(second.data['action'], 'duplicate')
        self.assertIn('Already logged', second.data['reply_text'])
        self.assertEqual(Transaction.objects.count(), 1)

    def test_budget_line_in_reply_when_over_budget(self):
        today = timezone.localdate()
        groceries = Category.objects.get(is_default=True, name='Groceries')
        Budget.objects.create(user=self.user, category=groceries, monthly_limit=Decimal('200'),
                              month=today.month, year=today.year)
        with patch('accounts.utils.send_budget_alert') as alert:
            r = self.send('250 groceries')
        self.assertIn('Over budget', r.data['reply_text'])
        alert.assert_called_once()  # existing email alert still fires

    # --- linking ---------------------------------------------------------
    def test_unlinked_user_gets_instructions(self):
        r = self.send('250 food', tg_id=999)
        self.assertEqual((r.status_code, r.data['action'], r.data['ok']), (200, 'not_linked', False))
        self.assertFalse(Transaction.objects.exists())

    def test_link_command_links_account(self):
        other = User.objects.create_user('second', 's@test.com', 'pass1234!')
        code = TelegramLinkCode.generate_for_user(other)
        r = self.send(f'/link {code.code.lower()}', tg_id=8880001)
        self.assertEqual(r.data['action'], 'linked')
        self.assertTrue(TelegramLink.objects.filter(user=other, telegram_user_id=8880001).exists())

    def test_start_deep_link_links_account(self):
        other = User.objects.create_user('third', 't@test.com', 'pass1234!')
        code = TelegramLinkCode.generate_for_user(other)
        r = self.send(f'/start {code.code}', tg_id=8880002)
        self.assertEqual(r.data['action'], 'linked')

    def test_link_errors_are_friendly(self):
        r = self.send('/link NOTAREALCODE', tg_id=8880003)
        self.assertEqual((r.status_code, r.data['action']), (200, 'link_error'))
        r = self.send('/link', tg_id=8880003)
        self.assertEqual(r.data['action'], 'link_error')

    def test_link_cannot_steal_telegram_id(self):
        other = User.objects.create_user('fourth', 'f@test.com', 'pass1234!')
        code = TelegramLinkCode.generate_for_user(other)
        r = self.send(f'/link {code.code}')  # self.TG_ID already linked to bot_user
        self.assertEqual(r.data['action'], 'link_error')
        self.assertEqual(TelegramLink.objects.get(telegram_user_id=self.TG_ID).user, self.user)

    def test_inactive_user(self):
        self.user.is_active = False
        self.user.save()
        r = self.send('250 food')
        self.assertEqual(r.data['action'], 'inactive')

    # --- commands --------------------------------------------------------
    def test_help_and_start(self):
        for cmd in ('/help', '/start', '/help@MySmartExpense2026Bot'):
            with self.subTest(cmd=cmd):
                r = self.send(cmd)
                self.assertEqual(r.data['action'], 'help')
                self.assertIn('/summary', r.data['reply_text'])

    def test_unknown_command(self):
        self.assertEqual(self.send('/dance').data['action'], 'unknown_command')

    def test_summary(self):
        self.send('+50000 salary')
        self.send('1200 groceries')
        self.send('300 food')
        r = self.send('/summary')
        self.assertEqual(r.data['action'], 'summary')
        self.assertIn('₹50,000', r.data['reply_text'])
        self.assertIn('₹1,500', r.data['reply_text'])
        self.assertIn('₹48,500', r.data['reply_text'])
        self.assertEqual(r.data['summary']['count'], 3)

    def test_summary_last_month(self):
        r = self.send('/summary last')
        self.assertEqual(r.data['summary']['count'], 0)

    def test_budget_command(self):
        self.assertIn('No budgets', self.send('/budget').data['reply_text'])
        today = timezone.localdate()
        food = Category.objects.get(is_default=True, name='Food & Dining')
        Budget.objects.create(user=self.user, category=food, monthly_limit=Decimal('1000'),
                              month=today.month, year=today.year)
        self.send('900 food')
        text = self.send('/budget').data['reply_text']
        self.assertIn('Food & Dining', text)
        self.assertIn('90%', text)

    def test_recent_and_categories(self):
        self.assertIn('No transactions', self.send('/recent').data['reply_text'])
        self.send('250 groceries')
        self.assertIn('Groceries', self.send('/recent').data['reply_text'])
        cats = self.send('/categories').data['reply_text']
        self.assertIn('Groceries', cats)
        self.assertIn('Salary', cats)
        self.assertNotIn('Salary', self.send('/categories EX').data['reply_text'])

    def test_undo_deletes_last_bot_transaction_only_once(self):
        self.send('100 food')
        self.send('200 groceries')
        r = self.send('/undo', message_id=5000)
        self.assertEqual(r.data['action'], 'undo')
        self.assertIn('₹200', r.data['reply_text'])
        self.assertEqual(list(Transaction.objects.values_list('amount', flat=True)), [Decimal('100.00')])
        # n8n retry of the same /undo must not delete another one
        retry = self.send('/undo', message_id=5000)
        self.assertEqual(retry.data['action'], 'duplicate')
        self.assertEqual(Transaction.objects.count(), 1)

    def test_undo_ignores_transactions_created_on_the_website(self):
        Transaction.objects.create(user=self.user, transaction_type='EX', amount=Decimal('999'),
                                   date=timezone.localdate())
        r = self.send('/undo')
        self.assertFalse(r.data['ok'])
        self.assertEqual(Transaction.objects.count(), 1)

    def test_undo_does_not_touch_other_users(self):
        other = User.objects.create_user('other_u', 'o@test.com', 'pass1234!')
        TelegramLink.objects.create(user=other, telegram_user_id=4440001)
        self.send('500 food', tg_id=4440001)
        r = self.send('/undo')
        self.assertFalse(r.data['ok'])
        self.assertEqual(Transaction.objects.filter(user=other).count(), 1)


class TelegramLinkPageDeepLinkTests(TestCase):
    @override_settings(TELEGRAM_BOT_USERNAME='MySmartExpense2026Bot')
    def test_generated_code_gets_one_tap_start_link(self):
        user = User.objects.create_user('deeplink_user', 'd@test.com', 'pass1234!')
        self.client.force_login(user)
        r = self.client.post(reverse('accounts:telegram-link'))
        code = TelegramLinkCode.objects.get(user=user).code
        self.assertContains(r, f'https://t.me/MySmartExpense2026Bot?start={code}')
