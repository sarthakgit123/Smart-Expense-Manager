"""
Simulate the n8n -> Django call for a Telegram message, without Telegram or n8n.

    python manage.py telegram_chat --telegram-user-id 111 "/help"
    python manage.py telegram_chat --telegram-user-id 111 "/link 1A2B3C4D5E6F7A8B"
    python manage.py telegram_chat --telegram-user-id 111 "250 groceries"
    python manage.py telegram_chat --telegram-user-id 111            # interactive chat

It sends exactly the JSON the n8n workflow sends to POST /api/telegram/message/
and prints reply_text, i.e. what the user would see in Telegram.

It WRITES to the configured database. Use USE_SQLITE=True for local testing.
"""
import itertools
import json
import secrets
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.test.utils import override_settings
from rest_framework.test import APIRequestFactory

from transactions.telegram_views import telegram_message


class Command(BaseCommand):
    help = 'Send a message to the Telegram bot endpoint as n8n would, and print the reply.'

    def add_arguments(self, parser):
        parser.add_argument('text', nargs='?', help='Message text. Omit for an interactive session.')
        parser.add_argument('--telegram-user-id', type=int, required=True, help='Simulated message.from.id')
        parser.add_argument('--username', default='', help='Simulated message.from.username')
        parser.add_argument('--message-id', type=int, help='Telegram message_id (default: unique per message)')
        parser.add_argument('--json', action='store_true', help='Print the full JSON response')
        parser.add_argument('--yes', action='store_true', help='Skip the confirmation for non-SQLite databases')

    def handle(self, *args, **opts):
        if opts['telegram_user_id'] <= 0:
            raise CommandError('--telegram-user-id must be positive')

        vendor = connection.vendor
        db_name = settings.DATABASES['default'].get('NAME')
        self.stdout.write(self.style.WARNING(f'Database: {vendor} ({db_name})'))
        if vendor != 'sqlite' and not opts['yes']:
            answer = input('This is not the local SQLite database. Messages will create real records. Continue? [y/N] ')
            if answer.strip().lower() != 'y':
                raise CommandError('Aborted. Set USE_SQLITE=True to use the local database.')

        # A throwaway secret for this process only; the view checks it like a real n8n call.
        secret = secrets.token_urlsafe(32)
        base_id = opts['message_id'] or int(time.time() * 1000) % 9_000_000_000
        counter = itertools.count()
        factory = APIRequestFactory()

        def send(text):
            message_id = opts['message_id'] if opts['message_id'] else base_id + next(counter)
            body = {
                'telegram_user_id': opts['telegram_user_id'],
                'message_id': message_id,
                'text': text,
                'telegram_username': opts['username'],
            }
            request = factory.post('/api/telegram/message/', body, format='json', HTTP_X_N8N_SECRET=secret)
            with override_settings(N8N_WEBHOOK_SECRET=secret):
                response = telegram_message(request)
            data = response.data
            if opts['json']:
                self.stdout.write(json.dumps(data, indent=2, ensure_ascii=False, default=str))
            elif 'reply_text' in data:
                style = self.style.SUCCESS if data.get('ok') else self.style.ERROR
                self.stdout.write(style(f'[{data.get("action")}]'))
                self.stdout.write(data['reply_text'])
            else:
                self.stdout.write(self.style.ERROR(f'HTTP {response.status_code}: {data}'))

        if opts['text'] is not None:
            send(opts['text'])
            return

        self.stdout.write('Interactive bot chat. Type a message, or "quit" to exit.')
        while True:
            try:
                text = input('you> ')
            except (EOFError, KeyboardInterrupt):
                self.stdout.write('')
                break
            if text.strip().lower() in ('quit', 'exit'):
                break
            send(text)
            self.stdout.write('')
