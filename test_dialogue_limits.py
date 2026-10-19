"""Offline spending-limit regressions; no real Telegram or OpenAI requests."""
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from bot import Bot, LimitReached


class DialogueLimitTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN': 'fake', 'OPENAI_API_KEY': 'fake',
            'OPENAI_MODEL': 'fake', 'TELEGRAM_CHAT_ID': '-100123',
            'OWNER_TELEGRAM_USER_ID': '1', 'DATA_DIR': directory.name,
            'VOICE_REMINDERS': 'false',
        }, clear=True)
        env.start()
        self.addCleanup(env.stop)
        network = patch('urllib.request.urlopen', side_effect=AssertionError('Network forbidden'))
        network.start()
        self.addCleanup(network.stop)
        self.bot = self.new_bot()
        self.day = datetime.now(ZoneInfo('Asia/Tashkent')).date().isoformat()
        self.response = {'output': [{'content': [{'type': 'output_text', 'text': 'Жавоб'}]}]}
        self.bot.db.execute('INSERT INTO questions(source,question_message,question) '
                            'VALUES(100,200,?)', ('Қайси қават?',))
        self.bot.db.commit()

    def new_bot(self):
        bot = Bot()
        self.addCleanup(bot.db.close)
        return bot

    def reply(self, message=201):
        return dict(chat={'id': -100123}, **{'from': {'id': 2}},
                    message_id=message, date=self.bot.started, text='6-қаватда ишлаяпмиз',
                    reply_to_message={'message_id': 200})

    def used(self, bot=None, day=None):
        return int((bot or self.bot).get_state('dialogue_attempts:' + (day or self.day), '0'))

    def test_default_budgets_and_two_report_reservations_are_independent(self):
        self.assertEqual((self.bot.max_calls, self.bot.max_dialogue_calls), (10, 10))
        with patch.object(self.bot, 'request', return_value=self.response) as request:
            for _ in range(8):
                self.bot.ai([])
            with self.assertRaises(LimitReached):
                self.bot.ai([])
            for _ in range(10):
                self.bot.ai([], dialogue=True)
            with self.assertRaises(LimitReached):
                self.bot.ai([], dialogue=True)
            for _ in range(2):
                self.bot.ai([], report=True)
            with self.assertRaises(LimitReached):
                self.bot.ai([], report=True)
            self.assertEqual(request.call_count, 20)
        self.assertEqual(self.used(), 10)
        self.assertEqual(self.bot.db.execute('SELECT n FROM calls WHERE day=?',
                                            (self.day,)).fetchone()[0], 10)

    def test_zero_disables_dialogue_and_invalid_config_fails_safely(self):
        with patch.dict(os.environ, MAX_DAILY_DIALOGUE_CALLS='0'):
            bot = self.new_bot()
        with patch.object(bot, 'request') as request:
            with self.assertRaises(LimitReached):
                bot.ai([], dialogue=True)
            with patch.object(bot, 'send') as send:
                bot.handle(self.reply())
                self.assertIn('ўчирилган', send.call_args.args[0])
                self.assertIn('сақланди', send.call_args.args[0])
            request.assert_not_called()
        self.assertEqual(self.used(bot), 0)
        for value in ('-1', '1.5', '', 'private-invalid-value'):
            with self.subTest(value=value), patch.dict(os.environ, MAX_DAILY_DIALOGUE_CALLS=value):
                with self.assertRaisesRegex(ValueError, '^MAX_DAILY_DIALOGUE_CALLS must be a non-negative integer.$'):
                    Bot()

    def test_existing_counts_survive_restart_and_config_changes(self):
        self.bot.set_state('dialogue_attempts:' + self.day, '12')
        restarted = self.new_bot()
        with patch.object(restarted, 'request') as request:
            with self.assertRaises(LimitReached):
                restarted.ai([], dialogue=True)
            request.assert_not_called()
        self.assertEqual(self.used(restarted), 12)
        with patch.dict(os.environ, MAX_DAILY_DIALOGUE_CALLS='13'):
            increased = self.new_bot()
        with patch.object(increased, 'request', return_value=self.response) as request:
            increased.ai([], dialogue=True)
            with self.assertRaises(LimitReached):
                increased.ai([], dialogue=True)
            request.assert_called_once()
        self.assertEqual(self.used(increased), 13)

    def test_tashkent_midnight_resets_only_the_new_day(self):
        self.bot.max_dialogue_calls = 1
        # Both instants are October 19 in UTC, but different dates in Tashkent.
        before = datetime(2026, 10, 19, 18, 59, 59, tzinfo=timezone.utc)
        after = datetime(2026, 10, 19, 19, 0, 0, tzinfo=timezone.utc)
        first, blocked, fresh = self.reply(201), self.reply(202), self.reply(203)
        with patch('bot.datetime', wraps=datetime) as clock, \
                patch.object(self.bot, 'request', return_value=self.response) as request, \
                patch.object(self.bot, 'send') as send:
            clock.now.side_effect = lambda tz: before.astimezone(tz)
            self.bot.handle(first)
            self.bot.handle(blocked)
            self.assertEqual(request.call_count, 1)
            self.assertIn('лимити тугади', send.call_args.args[0])
            clock.now.side_effect = lambda tz: after.astimezone(tz)
            self.bot.handle(blocked)  # Yesterday's blocked update is not retried.
            self.assertEqual(request.call_count, 1)
            self.bot.handle(fresh)
            self.assertEqual(request.call_count, 2)
        self.assertEqual(self.used(day='2026-10-19'), 1)
        self.assertEqual(self.used(day='2026-10-20'), 1)

    def test_blocked_reply_is_saved_explained_and_never_batched(self):
        self.bot.max_dialogue_calls = 1
        self.bot.reserve_dialogue()
        message = self.reply()

        def notice(text, reply):
            self.assertEqual(reply, message['message_id'])
            self.assertIn('Жавобингиз сақланди', text)
            self.assertIn('00:00', text)
            saved = self.bot.db.execute("SELECT text FROM events WHERE message=? "
                                        "AND kind='clarification_unverified'", (reply,)).fetchone()[0]
            self.assertIn(message['text'], saved)
            self.assertEqual(self.bot.db.execute("SELECT text FROM dialogue WHERE message=? "
                                                "AND role='user'", (reply,)).fetchone()[0], message['text'])
            return 300

        with patch.object(self.bot, 'request') as request, patch.object(self.bot, 'send', side_effect=notice) as send:
            self.bot.dispatch({'update_id': 1, 'message': message})
            self.bot.dispatch({'update_id': 1, 'message': message})
            self.assertTrue(self.bot.process_job())
            self.bot.dispatch({'update_id': 2, 'message': message})
            self.assertTrue(self.bot.process_job())
            send.assert_called_once()
            request.assert_not_called()
        restarted = self.new_bot()
        with patch.object(restarted, 'request') as request, patch.object(restarted, 'send') as send:
            restarted.handle(message)
            restarted.scheduled(datetime(2026, 10, 19, 8, tzinfo=ZoneInfo('Asia/Tashkent')))
            request.assert_not_called()
            send.assert_not_called()
        self.assertEqual(self.used(restarted), 1)
        self.assertEqual(self.bot.db.execute('SELECT count(*) FROM calls').fetchone()[0], 0)
        self.assertEqual(self.bot.db.execute("SELECT count(*) FROM events WHERE kind='user_report_unverified'").fetchone()[0], 0)
        self.assertEqual(self.bot.db.execute('SELECT count(*) FROM work_queue').fetchone()[0], 0)
        self.assertEqual(self.bot.get_state('last_media_error'), '')

    def test_successful_reply_is_not_charged_again_after_restart(self):
        message = self.reply()
        with patch.object(self.bot, 'request', return_value=self.response) as request, \
                patch.object(self.bot, 'send', return_value=300) as send:
            self.bot.handle(message)
            self.bot.handle(message)
            request.assert_called_once()
            send.assert_called_once()
        restarted = self.new_bot()
        with patch.object(restarted, 'request') as request, patch.object(restarted, 'send') as send:
            restarted.handle(message)
            request.assert_not_called()
            send.assert_not_called()
        self.assertEqual(self.used(restarted), 1)

    def test_failed_api_attempt_is_counted_once_even_after_restart(self):
        message = self.reply()
        with patch.object(self.bot, 'request', side_effect=TimeoutError) as request, \
                patch.object(self.bot, 'send') as send:
            with self.assertRaises(TimeoutError):
                self.bot.handle(message)
            self.bot.handle(message)
            request.assert_called_once()
            send.assert_not_called()
        restarted = self.new_bot()
        with patch.object(restarted, 'request') as request:
            restarted.handle(message)
            request.assert_not_called()
        self.assertEqual(self.used(restarted), 1)
        self.assertIn(message['text'], restarted.db.execute(
            "SELECT text FROM events WHERE kind='clarification_unverified'").fetchone()[0])

    def test_send_failure_does_not_repeat_paid_call(self):
        message = self.reply()
        with patch.object(self.bot, 'request', return_value=self.response) as request, \
                patch.object(self.bot, 'send', side_effect=TimeoutError) as send:
            with self.assertRaises(TimeoutError):
                self.bot.handle(message)
            self.bot.handle(message)
            request.assert_called_once()
            send.assert_called_once()
        self.assertEqual(self.used(), 1)

    def test_simultaneous_reservations_cannot_exceed_cap(self):
        barrier = threading.Barrier(8)

        def reserve(_):
            bot = Bot()  # Each thread owns its connection.
            try:
                barrier.wait(timeout=5)
                try:
                    bot.reserve_dialogue()
                    return True
                except LimitReached:
                    return False
            finally:
                bot.db.close()

        with patch.dict(os.environ, MAX_DAILY_DIALOGUE_CALLS='3'), ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(reserve, range(8))), 3)
        self.assertEqual(self.used(), 3)

    def test_health_shows_separate_usage_cap_remaining_and_reset(self):
        for used, remaining in ((2, 8), (10, 0), (12, 0)):
            self.bot.set_state('dialogue_attempts:' + self.day, used)
            with patch.object(self.bot, 'tg', side_effect=[{'id': 1}, {'status': 'administrator'}]), \
                    patch.object(self.bot, 'send') as send:
                self.bot.health()
            text = send.call_args.args[0]
            self.assertIn('Бугун AI сўровлари: 0/10', text)
            self.assertIn(f'Савол-жавоб сўровлари: {used}/10; қолди: {remaining}', text)
            self.assertIn('Тошкент вақти билан 00:00', text)
            self.assertNotIn('кунлик чеклов йўқ', text)


if __name__ == '__main__':
    unittest.main()
