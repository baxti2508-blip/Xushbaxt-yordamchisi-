import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from bot import Bot, LimitReached, command, response_text, split_text

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
