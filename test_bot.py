import json
import io
import urllib.error
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo
from bot import Bot, LimitReached, ServiceError, command, response_text, split_text

class Tests(unittest.TestCase):
    def test_setup_only_discloses_current_ids(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(TELEGRAM_BOT_TOKEN='fake', OPENAI_API_KEY='fake',
                       TELEGRAM_CHAT_ID='', OWNER_TELEGRAM_USER_ID='',
                       OPENAI_MODEL='fake', DATA_DIR=d)
            with patch.dict(os.environ, env):
                bot = Bot()
                with patch.object(bot, 'tg') as tg, patch.object(bot, 'ai') as ai:
                    msg = dict(chat={'id':-100123}, **{'from':{'id':42}},
                               text='/id', message_id=1, date=1)
                    bot.handle(msg)
                    self.assertEqual(tg.call_args.kwargs['chat_id'], -100123)
                    self.assertIn('User ID: 42', tg.call_args.kwargs['text'])
                    for text in ('private text', '/status', '/tahlil'):
                        bot.handle({**msg, 'text':text})
                    ai.assert_not_called()
                    self.assertEqual(tg.call_count, 1)
                    self.assertEqual(bot.chat, 0)
                    self.assertEqual(bot.owner, 0)
                    self.assertEqual(bot.db.execute('SELECT count(*) FROM events').fetchone()[0],0)
                bot.db.close()

    def test_caption_and_reply_analysis(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(TELEGRAM_BOT_TOKEN='fake', OPENAI_API_KEY='fake',
                       TELEGRAM_CHAT_ID='-100123', OWNER_TELEGRAM_USER_ID='1',
                       OPENAI_MODEL='fake', DATA_DIR=d)
            with patch.dict(os.environ, env):
                bot = Bot()
                msg = dict(chat={'id':-100123}, **{'from':{'id':1}},
                           message_id=10, date=1, video={'file_id':'fake'},
                           caption='/tahlil@Urgench10QavatNazorat_bot')
                with patch.object(bot, 'analyze') as analyze, patch.object(bot, 'send') as send:
                    bot.handle(msg)
                    analyze.assert_called_once_with(msg)
                    analyze.reset_mock()
                    reply = {k:v for k,v in msg.items() if k not in ('video', 'caption')}
                    reply.update(text='/tahlil', reply_to_message=msg)
                    bot.handle(reply)
                    analyze.assert_called_once_with(msg)
                    analyze.reset_mock()
                    bot.handle({**msg, 'from':{'id':2}})
                    analyze.assert_not_called()
                    self.assertIn('OWNER_TELEGRAM_USER_ID', send.call_args.args[0])
                bot.db.close()

    def test_automatic_media_only_in_configured_group(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(TELEGRAM_BOT_TOKEN='fake', OPENAI_API_KEY='fake',
                       TELEGRAM_CHAT_ID='-100123', OWNER_TELEGRAM_USER_ID='1',
                       OPENAI_MODEL='fake', DATA_DIR=d, AUTO_ANALYZE='false')
            with patch.dict(os.environ, env):
                bot = Bot()
                msg = dict(chat={'id':-100123}, **{'from':{'id':2}},
                           message_id=20, date=bot.started, video={'file_id':'fake'})
                with patch.object(bot, 'analyze') as analyze:
                    bot.handle(msg)
                    analyze.assert_called_once_with(msg)
                    analyze.reset_mock()
                    bot.handle({**msg, 'chat':{'id':5}})
                    bot.handle({**msg, 'date':bot.started-1})
                    analyze.assert_not_called()
                bot.db.close()

    def test_tasks_schedule_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(TELEGRAM_BOT_TOKEN='fake', OPENAI_API_KEY='fake',
                       TELEGRAM_CHAT_ID='-100123', OWNER_TELEGRAM_USER_ID='1',
                       OPENAI_MODEL='fake', DATA_DIR=d)
            with patch.dict(os.environ, env):
                bot = Bot()
                msg = dict(chat={'id':-100123}, **{'from':{'id':1}},
                           message_id=30, date=bot.started,
                           text='/vazifa 2026-10-01 | Жумонбек | Қолип')
                with patch.object(bot, 'send') as send, patch.object(bot, 'status') as status:
                    bot.handle({**msg, 'from':{'id':2}})
                    self.assertEqual(bot.db.execute('SELECT count(*) FROM tasks').fetchone()[0], 0)
                    bot.handle(msg)
                    self.assertIn('Жумонбек', bot.task_summary())
                    bot.handle({**msg, 'text':'/vazifa 2026-99-99 | A | B'})
                    self.assertEqual(bot.db.execute('SELECT count(*) FROM tasks').fetchone()[0], 1)
                    now = datetime(2026,10,9,20,0,tzinfo=ZoneInfo('Asia/Tashkent'))
                    bot.scheduled(now)
                    self.assertEqual([c.args for c in status.call_args_list], [(7,), (1,)])
                    bot.scheduled(now)
                    self.assertEqual(status.call_count, 2)
                    self.assertTrue(any('Муддати ўтган' in c.args[0] for c in send.call_args_list))
                    bot.handle({**msg, 'text':'/bajarildi 1'})
                    self.assertEqual(bot.db.execute('SELECT status FROM tasks').fetchone()[0], 'done')
                since = bot.monitor_since
                bot.db.close()
                restored = Bot()
                self.assertEqual(restored.monitor_since, since)
                with patch.object(restored, 'status') as status:
                    restored.scheduled(now)
                    status.assert_not_called()
                self.assertEqual(restored.db.execute('SELECT status FROM tasks').fetchone()[0], 'done')
                restored.db.close()

    def test_reports_and_text_queue(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(TELEGRAM_BOT_TOKEN='fake', OPENAI_API_KEY='fake',
                       TELEGRAM_CHAT_ID='-100123', OWNER_TELEGRAM_USER_ID='1',
                       OPENAI_MODEL='fake', DATA_DIR=d, MAX_DAILY_CALLS='3')
            with patch.dict(os.environ, env):
                bot = Bot()
                bot.reserve()
                with self.assertRaises(LimitReached):
                    bot.reserve()
                bot.reserve(report=True)
                bot.reserve(report=True)
                with self.assertRaises(LimitReached):
                    bot.reserve(report=True)
                msg = dict(chat={'id':-100123}, **{'from':{'id':2}},
                           message_id=40, date=bot.started, text='Қолип ҳали тугамади')
                bot.handle(msg)
                now = datetime(2026,10,8,1,0,tzinfo=ZoneInfo('Asia/Tashkent'))
                with patch.object(bot, 'ai', side_effect=LimitReached), patch.object(bot, 'send') as send:
                    bot.status(1)
                    self.assertIn('лимит', send.call_args.args[0])
                    with self.assertRaises(LimitReached):
                        bot.scheduled(now)
                    self.assertEqual(bot.get_state('text_cursor'), '')
                bot.set_state('text_check', 0)
                with patch.object(bot, 'ai', return_value='Тугамаган иш ҳақида баёнот') as ai, patch.object(bot, 'send'):
                    bot.scheduled(now)
                    ai.assert_called_once()
                    self.assertTrue(bot.get_state('text_cursor'))
                bot.db.close()

    def test_quota_and_rate_errors_are_distinct_and_private(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(TELEGRAM_BOT_TOKEN='fake', OPENAI_API_KEY='fake',
                       TELEGRAM_CHAT_ID='-100123', OWNER_TELEGRAM_USER_ID='1',
                       OPENAI_MODEL='fake', DATA_DIR=d)
            with patch.dict(os.environ, env):
                bot = Bot()
                cases = [('organization_spend_limit_exceeded', 'insufficient_quota', 'баланси'),
                         ('rate_limit_exceeded', 'rate_limit_error', 'тезлиги'),
                         (None, None, 'баланс/квота')]
                for code, kind, expected in cases:
                    body = json.dumps({'error':{'code':code,'type':kind,'message':'secret-never-echo'}}).encode()
                    error = urllib.error.HTTPError('https://example.invalid',429,'error',{},io.BytesIO(body))
                    with patch.object(bot, 'reserve'), patch.object(bot, 'request', side_effect=error):
                        with self.assertRaises(ServiceError) as raised:
                            bot.ai([])
                        self.assertIn(expected, str(raised.exception))
                        self.assertNotIn('secret-never-echo', bot.get_state('last_error'))
                bot.db.close()

    def test_response(self):
        self.assertEqual(response_text({'output':[{'content':[{'type':'output_text','text':'ok'}]}]}),'ok')
        self.assertEqual(command('/status@Urgench10QavatNazorat_bot'),'/status')
        self.assertTrue(all(len(s) <= 3000 for s in split_text('А'*9001)))

    def test_limits_and_isolation(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'baseline.json'
            p.write_text(json.dumps({'confirmed_values':[{'value':3.30}]}))
            before = p.read_bytes()
            env = dict(TELEGRAM_BOT_TOKEN='fake',OPENAI_API_KEY='fake',
                TELEGRAM_CHAT_ID='-100123',OWNER_TELEGRAM_USER_ID='1',OPENAI_MODEL='fake',
                MAX_DAILY_CALLS='1',DATA_DIR=d,BASELINE_FILE=str(p))
            with patch.dict(os.environ,env):
                bot = Bot()
                bot.reserve()
                with self.assertRaises(LimitReached):
                    bot.reserve()
                bot.handle({'chat':{'id':5},'text':'private'})
                bot.handle({'chat':{'id':-100123},'from':{'is_bot':True},'text':'bot'})
                self.assertEqual(bot.db.execute('SELECT count(*) FROM events').fetchone()[0],0)
                with patch.object(bot, 'tg') as tg, patch.object(bot, 'ai') as ai:
                    bot.handle({'chat':{'id':-100123},'from':{'id':2},'text':'/status','message_id':2,'date':1})
                    self.assertIn('OWNER_TELEGRAM_USER_ID', tg.call_args.kwargs['text'])
                    bot.handle({'chat':{'id':5},'from':{'id':1},'text':'/id','message_id':3,'date':1})
                    self.assertEqual(tg.call_args.kwargs['chat_id'], 5)
                    self.assertIn('TELEGRAM_CHAT_ID', tg.call_args.kwargs['text'])
                    ai.assert_not_called()
                    self.assertEqual(bot.db.execute('SELECT count(*) FROM events').fetchone()[0],0)
                self.assertEqual(p.read_bytes(),before)
                bot.db.close()

if __name__ == '__main__':
    unittest.main()
