"""Offline regressions: every unmocked external request is prohibited."""
import io
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest.mock import patch

from bot import Bot, ServiceError


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN': 'fake-token', 'OPENAI_API_KEY': 'fake-key',
            'OPENAI_MODEL': 'fake-model', 'TELEGRAM_CHAT_ID': '-100123',
            'OWNER_TELEGRAM_USER_ID': '1', 'DATA_DIR': self.directory.name,
            'DELETE_WEBHOOK_ON_START': 'false',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.network = patch('urllib.request.urlopen', side_effect=AssertionError('Network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.bot = Bot()
        self.addCleanup(self.bot.db.close)

    def message(self, number, **fields):
        return dict(chat={'id': -100123}, **{'from': {'id': 1}},
                    message_id=number, date=self.bot.started, **fields)

    def test_durable_queue_offset_dedup_and_restart(self):
        update = {'update_id': 20, 'message': self.message(10, video={'file_id': 'fake'})}
        with patch.object(self.bot, 'analyze') as analyze:
            self.bot.dispatch(update)
            self.bot.dispatch(update)
            analyze.assert_not_called()
        self.assertEqual(self.bot.get_state('offset'), '21')
        self.assertEqual(self.bot.db.execute('SELECT count(*) FROM work_queue').fetchone()[0], 1)
        restarted = Bot()
        try:
            with patch.object(restarted, 'analyze') as analyze:
                self.assertTrue(restarted.process_job())
                analyze.assert_called_once_with(update['message'])
                self.assertFalse(restarted.process_job())
        finally:
            restarted.db.close()

    def test_running_polling_answers_commands_while_video_is_blocked(self):
        entered, release = threading.Event(), threading.Event()
        replies, polls = [], []
        owner = self

        def slow_analysis(bot, message):
            entered.set()
            if not release.wait(5):
                raise AssertionError('Test failed to release video worker')

        def telegram(bot, method, **params):
            if method == 'getWebhookInfo':
                return {'url': ''}
            if method == 'getUpdates':
                polls.append(params['offset'])
                if len(polls) == 1:
                    return [{'update_id': 1, 'message': owner.message(1, video={'file_id': 'fake'})}]
                if len(polls) == 2:
                    owner.assertTrue(entered.wait(3), 'Actual worker never started')
                    return [{'update_id': 2, 'message': owner.message(2, text='/id')},
                            {'update_id': 3, 'message': owner.message(3, text='/holat')}]
                release.set()
                raise KeyboardInterrupt()
            if method == 'getMe':
                return {'id': 99, 'can_read_all_group_messages': True}
            if method == 'getChatMember':
                return {'status': 'administrator'}
            if method == 'sendMessage':
                owner.assertTrue(entered.is_set())
                owner.assertFalse(release.is_set(), 'Command waited for video completion')
                replies.append(params['text'])
                return {'message_id': 100 + len(replies)}
            raise AssertionError(method)

        with patch.object(Bot, 'tg', telegram), patch.object(Bot, 'analyze', slow_analysis), \
                patch.object(Bot, 'startup_check'), patch.object(Bot, 'scheduled'), \
                patch.object(Bot, 'retry_media'):
            try:
                with self.assertRaises(KeyboardInterrupt):
                    self.bot.run()
            finally:
                release.set()
        self.assertEqual(polls, [0, 2, 4])
        self.assertTrue(any('Chat ID:' in text for text in replies))
        self.assertTrue(any('Код SHA256:' in text for text in replies))
        self.assertIn('#3 text', self.bot.get_state('last_received'))

    def test_webhook_opt_in_preserves_pending_messages_and_redacts_url(self):
        secret_url = 'https://example.invalid/private-secret'
        with patch.object(self.bot, 'tg', return_value={'url': secret_url}) as tg:
            with self.assertRaises(ServiceError) as caught:
                self.bot.prepare_polling()
            self.assertNotIn(secret_url, str(caught.exception))
            self.assertNotIn(secret_url, self.bot.get_state('last_poll_error'))
            tg.assert_called_once_with('getWebhookInfo')
        with patch.dict(os.environ, DELETE_WEBHOOK_ON_START='true'), \
                patch.object(self.bot, 'tg', side_effect=[{'url': secret_url}, True, {'url': ''}]) as tg:
            self.bot.prepare_polling()
            self.assertEqual(tg.call_args_list[1].args, ('deleteWebhook',))
            self.assertEqual(tg.call_args_list[1].kwargs, {'drop_pending_updates': False})

    def test_missing_ai_settings_leave_id_available_and_make_no_api_call(self):
        with patch.dict(os.environ, OPENAI_API_KEY='', OPENAI_MODEL=''):
            bot = Bot()
        try:
            with patch.object(bot, 'tg', return_value={}) as tg:
                bot.dispatch({'update_id': 2, 'message': self.message(2, text='/id')})
                tg.assert_called_once()
            with self.assertRaises(ServiceError):
                bot.ai([])
        finally:
            bot.db.close()

    def test_service_failure_and_failed_warning_do_not_stick_job(self):
        self.bot.dispatch({'update_id': 10, 'message': self.message(10, video={'file_id': 'fake'})})
        with patch.object(self.bot, 'analyze', side_effect=ServiceError('OpenAI HTTP 401')), \
                patch.object(self.bot, 'send', side_effect=RuntimeError('secret URL')):
            self.assertTrue(self.bot.process_job())
        self.assertEqual(self.bot.db.execute('SELECT count(*) FROM work_queue').fetchone()[0], 0)
        self.assertEqual(self.bot.db.execute('SELECT count(*) FROM media_queue').fetchone()[0], 1)
        self.assertNotIn('secret', self.bot.get_state('last_media_error'))

    def test_openai_http_errors_are_classified_without_response_secrets(self):
        for status, code, expected in [(401, '', 'калити'), (403, '', 'рухсат'),
                                       (404, '', 'модель'), (429, 'insufficient_quota', 'баланси'),
                                       (429, 'rate_limit_exceeded', 'тезлиги'), (500, '', 'HTTP 500')]:
            body = json.dumps({'error': {'code': code, 'message': 'fake-key private-secret'}}).encode()
            err = urllib.error.HTTPError('https://private-secret', status, 'secret', {}, io.BytesIO(body))
            with self.assertRaises(ServiceError) as caught:
                self.bot.api_error(err)
            self.assertIn(expected, str(caught.exception))
            self.assertNotIn('private-secret', self.bot.get_state('last_error'))
            self.assertNotIn('fake-key', str(caught.exception))

    def test_telegram_transport_timeouts(self):
        with patch.object(self.bot, 'request', return_value={'ok': True, 'result': []}) as request:
            self.bot.tg('getUpdates', timeout=40)
            self.assertEqual(request.call_args.kwargs['timeout'], 50)
            self.bot.tg('getMe')
            self.assertEqual(request.call_args.kwargs['timeout'], 10)

    def test_unrelated_group_and_bot_messages_are_not_queued(self):
        m = self.message(1, text='private content')
        m['chat']['id'] = -999
        self.bot.dispatch({'update_id': 1, 'message': m})
        m['chat']['id'] = -100123
        m['from']['is_bot'] = True
        self.bot.dispatch({'update_id': 2, 'message': m})
        self.assertEqual(self.bot.db.execute('SELECT count(*) FROM work_queue').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
