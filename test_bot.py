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
                bot.handle({'chat':{'id':-100123},'from':{'id':2},'text':'/status','message_id':2,'date':1})
                self.assertEqual(p.read_bytes(),before)
                bot.db.close()

if __name__ == '__main__':
    unittest.main()
