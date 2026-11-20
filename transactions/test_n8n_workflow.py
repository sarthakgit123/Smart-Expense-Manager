"""
Phase 3 tests: the exported n8n workflow stays consistent with the Django API
and never contains secrets; the telegram_chat simulator works.
"""
import json
import re
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from transactions.models import TelegramLink, TelegramLinkCode, Transaction

WORKFLOW_PATH = Path(settings.BASE_DIR) / 'n8n' / 'telegram_expense_workflow.json'
BOT_TOKEN_RE = re.compile(r'\d{6,}:[A-Za-z0-9_-]{30,}')


class N8nWorkflowFileTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.raw = WORKFLOW_PATH.read_text(encoding='utf-8')
        cls.wf = json.loads(cls.raw)
        cls.nodes = {n['name']: n for n in cls.wf['nodes']}

    def test_contains_no_secrets(self):
        self.assertIsNone(BOT_TOKEN_RE.search(self.raw), 'Telegram bot token found in workflow JSON')
        for node in self.wf['nodes']:
            for cred in node.get('credentials', {}).values():
                self.assertEqual(cred.get('id'), '', f'{node["name"]}: credential id must be blank in the export')
        configured = getattr(settings, 'N8N_WEBHOOK_SECRET', '')
        if configured:
            self.assertNotIn(configured, self.raw)
        self.assertNotIn('"value": "X-N8N-Secret"', self.raw)

    def test_inactive_on_import(self):
        self.assertFalse(self.wf['active'])

    def test_calls_the_chat_endpoint_with_header_auth(self):
        node = self.nodes['Send to Django']
        params = node['parameters']
        self.assertEqual(params['method'], 'POST')
        self.assertTrue(params['url'].endswith(reverse('telegram-message')))
        self.assertEqual(params['genericAuthType'], 'httpHeaderAuth')
        self.assertIn('httpHeaderAuth', node['credentials'])
        for field in ('telegram_user_id', 'message_id', 'text', 'telegram_username'):
            self.assertIn(field, params['jsonBody'])
        self.assertIn('message.from.id', params['jsonBody'])       # identity from Telegram, not from text
        self.assertIn('message.message_id', params['jsonBody'])

    def test_retries_and_error_branch(self):
        node = self.nodes['Send to Django']
        self.assertTrue(node['retryOnFail'])
        self.assertGreaterEqual(node['maxTries'], 2)
        self.assertEqual(node['onError'], 'continueErrorOutput')
        outputs = self.wf['connections']['Send to Django']['main']
        self.assertEqual(outputs[0][0]['node'], 'Reply')
        self.assertEqual(outputs[1][0]['node'], 'Reply: server error')

    def test_reply_uses_reply_text_without_attribution(self):
        reply = self.nodes['Reply']['parameters']
        self.assertIn('reply_text', reply['text'])
        self.assertFalse(reply['additionalFields']['appendAttribution'])

    def test_all_connections_point_to_existing_nodes(self):
        for source, conn in self.wf['connections'].items():
            self.assertIn(source, self.nodes)
            for branch in conn['main']:
                for target in branch:
                    self.assertIn(target['node'], self.nodes)

    def test_successful_executions_not_stored(self):
        self.assertEqual(self.wf['settings'].get('saveDataSuccessExecution'), 'none')


class TelegramChatCommandTests(TestCase):
    def run_cmd(self, text, tg_id=31337):
        out = StringIO()
        call_command('telegram_chat', text, telegram_user_id=tg_id, stdout=out)
        return out.getvalue()

    def test_unlinked_then_link_then_log(self):
        self.assertIn('not_linked', self.run_cmd('250 groceries'))
        user = User.objects.create_user('cmd_user', 'c@test.com', 'pass1234!')
        code = TelegramLinkCode.generate_for_user(user).code
        self.assertIn('[linked]', self.run_cmd(f'/link {code}'))
        self.assertTrue(TelegramLink.objects.filter(user=user, telegram_user_id=31337).exists())
        output = self.run_cmd('250 groceries')
        self.assertIn('transaction_created', output)
        self.assertEqual(Transaction.objects.filter(user=user).count(), 1)
