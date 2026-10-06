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
    def test_startup_checks_permissions_once_without_paid_ai(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(TELEGRAM_BOT_TOKEN='fake', OPENAI_API_KEY='fake',
                       TELEGRAM_CHAT_ID='-100123', OWNER_TELEGRAM_USER_ID='1',
                       OPENAI_MODEL='fake', DATA_DIR=d)
            with patch.dict(os.environ, env):
                bot = Bot()
                with patch.object(bot, 'tg', side_effect=[{'id':10,'username':'TestBot'}, {'status':'member'}]), \
                     patch.object(bot, 'send') as send, patch.object(bot, 'ai') as ai:
                    bot.startup_check()
                    self.assertIn('Privacy Mode', send.call_args.args[0])
                    self.assertIn('@TestBot', send.call_args.args[0])
                    bot.startup_check()
                    send.assert_called_once()
                    ai.assert_not_called()
                bot.db.close()
                bot = Bot()
                with patch.object(bot, 'tg') as tg:
                    bot.startup_check()
                    tg.assert_not_called()
                bot.db.close()

    def test_telegram_external_video_reply_is_analyzed(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(TELEGRAM_BOT_TOKEN='fake', OPENAI_API_KEY='fake',
                       TELEGRAM_CHAT_ID='-100123', OWNER_TELEGRAM_USER_ID='1',
                       OPENAI_MODEL='fake', DATA_DIR=d)
            with patch.dict(os.environ, env):
                bot = Bot()
                msg = dict(chat={'id':-100123}, **{'from':{'id':1}},
                           message_id=124, date=bot.started, text='/tahlil',
                           external_reply={'origin':{'date':bot.started-60},
                                           'chat':{'id':-100999}, 'message_id':7,
                                           'video':{'file_id':'fake'}})
                with patch.object(bot, 'analyze') as analyze:
                    bot.handle(msg)
                    target = analyze.call_args.args[0]
                    self.assertEqual(target['video']['file_id'], 'fake')
                    self.assertEqual(target['message_id'], 124)
                    self.assertEqual(target['chat']['id'], -100123)
                    self.assertEqual(target['date'], bot.started-60)
                bot.db.close()

    def test_failed_automatic_media_survives_restart_and_retries_without_command(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(TELEGRAM_BOT_TOKEN='fake', OPENAI_API_KEY='fake',
                       TELEGRAM_CHAT_ID='-100123', OWNER_TELEGRAM_USER_ID='1',
                       OPENAI_MODEL='fake', DATA_DIR=d)
            with patch.dict(os.environ, env):
                bot = Bot()
                msg = dict(chat={'id':-100123}, **{'from':{'id':2}},
                           message_id=123, date=bot.started, video={'file_id':'fake'})
                with patch.object(bot, 'analyze', side_effect=ServiceError('temporary')):
                    with self.assertRaises(ServiceError):
                        bot.handle(msg)
                bot.db.close()
                bot = Bot()
                bot.db.execute('UPDATE media_queue SET retry_at=0')
                bot.db.commit()
                with patch.object(bot, 'analyze') as analyze:
                    bot.retry_media()
                    analyze.assert_called_once_with(msg)
                bot.db.execute('UPDATE media_queue SET retry_at=0')
                bot.db.commit()
                with patch.object(bot, 'analyze', side_effect=LimitReached):
                    bot.retry_media()
                self.assertEqual(bot.db.execute('SELECT attempts FROM media_queue').fetchone()[0], 2)
                bot.db.execute('UPDATE media_queue SET retry_at=0')
                bot.db.commit()
                with patch.object(bot, 'analyze', side_effect=ServiceError('temporary')):
                    bot.retry_media()
                with patch.object(bot, 'analyze') as analyze:
                    bot.retry_media()
                    analyze.assert_not_called()
                bot.db.close()

    def test_health_distinguishes_group_privacy_from_analysis_failure(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(TELEGRAM_BOT_TOKEN='fake', OPENAI_API_KEY='fake',
                       TELEGRAM_CHAT_ID='-100123', OWNER_TELEGRAM_USER_ID='1',
                       OPENAI_MODEL='fake', DATA_DIR=d)
            with patch.dict(os.environ, env):
                bot = Bot()
                bot.set_state('last_media_error', 'Медиа таҳлили: файл катта.')
                for admin, privacy_off, expected in [
                        (False,False,'Privacy Mode ёқилган'),
                        (True,False,'оддий гуруҳ хабарларини олиши мумкин'),
                        (False,True,'оддий гуруҳ хабарларини олиши мумкин')]:
                    with patch.object(bot, 'tg', side_effect=[
                            {'id':10,'can_read_all_group_messages':privacy_off},
                            {'status':'administrator' if admin else 'member'}]), \
                         patch.object(bot, 'send') as send:
                        bot.health()
                        self.assertIn(expected, send.call_args.args[0])
                        self.assertIn('файл катта', send.call_args.args[0])
                bot.db.close()

    def test_dialogue_bypasses_media_limit_and_counts_attempts(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(TELEGRAM_BOT_TOKEN='fake', OPENAI_API_KEY='fake',
                       TELEGRAM_CHAT_ID='-100123', OWNER_TELEGRAM_USER_ID='1',
                       OPENAI_MODEL='fake', DATA_DIR=d, MAX_DAILY_CALLS='3')
            with patch.dict(os.environ, env):
                bot = Bot()
                response = {'output':[{'content':[{'type':'output_text','text':'Жавоб'}]}]}
                with patch.object(bot, 'request', return_value=response), patch.object(bot, 'reserve') as reserve:
                    for _ in range(12):
                        self.assertEqual(bot.ai([{'type':'input_text','text':'Савол'}], dialogue=True), 'Жавоб')
                    reserve.assert_not_called()
                day = datetime.now(ZoneInfo('Asia/Tashkent')).date().isoformat()
                self.assertEqual(bot.get_state('dialogue_attempts:' + day), '12')
                bot.db.close()

    def test_questions_dedup_no_daily_limit_and_worker_reply_link(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(TELEGRAM_BOT_TOKEN='fake', OPENAI_API_KEY='fake',
                       TELEGRAM_CHAT_ID='-100123', OWNER_TELEGRAM_USER_ID='1',
                       OPENAI_MODEL='fake', DATA_DIR=d)
            with patch.dict(os.environ, env):
                bot = Bot()
                msg = dict(chat={'id':-100123}, **{'from':{'id':2}},
                           message_id=100, date=bot.started, caption='6-қават')
                with patch.object(bot, 'send', return_value=200) as send, \
                     patch.object(bot, 'ai', return_value='Паспорт келганда юборинг.') as ai:
                    bot.ask_question(msg, 'SAVOL: Бетон паспорти борми?')
                    bot.ask_question(msg, 'SAVOL: Бетон паспорти борми?')
                    self.assertEqual(send.call_count, 1)
                    bot.ask_question(dict(msg, message_id=101), 'SAVOL: YOQ')
                    self.assertEqual(send.call_count, 1)
                    for ident in (101,102,103):
                        bot.ask_question(dict(msg, message_id=ident), 'SAVOL: Иш санаси қайси?')
                    self.assertEqual(send.call_count, 4)
                    reply = dict(msg, message_id=104, text='Паспорт эртага келади',
                                 reply_to_message={'message_id':200})
                    bot.handle(reply)
                    self.assertTrue(ai.call_args.kwargs['dialogue'])
                self.assertEqual(bot.db.execute('SELECT answer_message,answered_by FROM questions WHERE source=100').fetchone(),
                                 (104,2))
                saved = bot.db.execute("SELECT text FROM events WHERE kind='clarification_unverified'").fetchone()[0]
                self.assertIn('Манба #100', saved)
                self.assertIn('Паспорт эртага келади', saved)
                bot.db.close()

    def test_defect_owner_evidence_dedup_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(TELEGRAM_BOT_TOKEN='fake', OPENAI_API_KEY='fake',
                       TELEGRAM_CHAT_ID='-100123', OWNER_TELEGRAM_USER_ID='1',
                       OPENAI_MODEL='fake', DATA_DIR=d)
            with patch.dict(os.environ, env):
                bot = Bot()
                msg = dict(chat={'id':-100123}, **{'from':{'id':2}},
                           message_id=90, date=bot.started,
                           text='/nuqson 2026-10-08 | Уста | 6-қават А-1 | Чизма билан солиштириш')
                with patch.object(bot, 'send'):
                    bot.handle(msg)
                    self.assertEqual(bot.db.execute('SELECT count(*) FROM defects').fetchone()[0], 0)
                    msg['from']['id'] = 1
                    msg['text'] = '/nuqson 2026-02-30 | Уста | А-1 | Камчилик'
                    bot.handle(msg)
                    self.assertEqual(bot.db.execute('SELECT count(*) FROM defects').fetchone()[0], 0)
                    msg['text'] = '/nuqson 2026-10-08 | Уста | 6-қават А-1 | Чизма билан солиштириш'
                    bot.handle(msg)
                    bot.handle(msg)
                    self.assertEqual(bot.db.execute('SELECT count(*) FROM defects').fetchone()[0], 1)
                    msg.update(message_id=91, text='/yopildi 1')
                    bot.handle(msg)
                    self.assertEqual(bot.db.execute('SELECT status FROM defects').fetchone()[0], 'open')
                bot.db.close()
                bot = Bot()
                self.assertIn('6-қават А-1', bot.defect_summary())
                msg['reply_to_message'] = {'message_id':92, 'photo':[{'file_id':'fake'}]}
                with patch.object(bot, 'send'), patch.object(bot, 'ai') as ai:
                    bot.handle(msg)
                    ai.assert_not_called()
                self.assertEqual(bot.db.execute('SELECT status,evidence,closed_by FROM defects').fetchone(),
                                 ('closed', 92, 1))
                bot.db.close()

    def test_voice_reminders_daily_restart_cache_and_retry(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(TELEGRAM_BOT_TOKEN='fake', OPENAI_API_KEY='fake',
                       TELEGRAM_CHAT_ID='-100123', OWNER_TELEGRAM_USER_ID='1',
                       OPENAI_MODEL='fake', DATA_DIR=d, VOICE_REMINDERS='true')
            now = datetime(2026, 10, 7, 9, tzinfo=ZoneInfo('Asia/Tashkent'))
            with patch.dict(os.environ, env):
                bot = Bot()
                with patch.object(bot, 'speech', return_value=b'mp3') as speech, \
                     patch.object(bot, 'send_voice') as send:
                    bot.voice_reminders(now.replace(hour=8))
                    speech.assert_not_called()
                    bot.voice_reminders(now)
                    bot.voice_reminders(now)
                    self.assertEqual(speech.call_count, 3)
                    self.assertEqual(send.call_count, 3)
                    safety = bot.voice_text('safety')
                    self.assertIn('йўриқнома суҳбатини', safety)
                    self.assertIn('журналларига ҳақиқий сана', safety)
                    self.assertIn('Ўтказилмаган суҳбатни', safety)
                bot.db.close()
                bot = Bot()
                with patch.object(bot, 'speech') as speech, patch.object(bot, 'send_voice') as send:
                    bot.voice_reminders(now)
                    send.assert_not_called()
                    send.side_effect = RuntimeError('network')
                    tomorrow = now.replace(day=8)
                    bot.voice_reminders(tomorrow)
                    self.assertEqual(send.call_count, 3)
                    bot.voice_reminders(tomorrow)
                    self.assertEqual(send.call_count, 3)
                    speech.assert_not_called()
                    send.side_effect = None
                    for trade in ('gasblock', 'concrete', 'safety'):
                        bot.set_state(f'voice:{trade}:2026-10-08:retry', 0)
                    bot.voice_reminders(tomorrow)
                    self.assertEqual(send.call_count, 6)
                    speech.assert_not_called()
                bot.db.close()

    def test_tts_payload_cap_and_telegram_voice_upload(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(TELEGRAM_BOT_TOKEN='fake', OPENAI_API_KEY='fake',
                       TELEGRAM_CHAT_ID='-100123', OWNER_TELEGRAM_USER_ID='1',
                       OPENAI_MODEL='fake', DATA_DIR=d)
            with patch.dict(os.environ, env):
                bot = Bot()
                with patch('urllib.request.urlopen') as urlopen:
                    urlopen.return_value.__enter__.side_effect = [
                        io.BytesIO(b'mp3'), io.BytesIO(b'mp3'), io.BytesIO(b'mp3'),
                        io.BytesIO(b'{"ok":true,"result":{}}')]
                    self.assertEqual(bot.speech('Эслатма', '2026-10-07'), b'mp3')
                    payload = json.loads(urlopen.call_args.args[0].data)
                    self.assertEqual(payload['model'], 'gpt-4o-mini-tts')
                    self.assertEqual(payload['response_format'], 'mp3')
                    self.assertEqual(payload['input'], 'Эслатма')
                    bot.speech('Эслатма', '2026-10-07')
                    bot.speech('Эслатма', '2026-10-07')
                    with self.assertRaises(LimitReached):
                        bot.speech('Эслатма', '2026-10-07')
                    bot.send_voice(b'\x00mp3-binary', 'AI овоз')
                    req = urlopen.call_args.args[0]
                    self.assertTrue(req.full_url.endswith('/sendVoice'))
                    self.assertIn(b'filename="reminder.mp3"', req.data)
                    self.assertIn(b'\x00mp3-binary', req.data)
                    self.assertIn(b'-100123', req.data)
                    self.assertNotIn(b'fake', req.data)
                    self.assertEqual(bot.db.execute('SELECT count(*) FROM calls').fetchone()[0], 0)
                bot.db.close()

    def test_audio_and_video_are_combined_with_transcript(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(TELEGRAM_BOT_TOKEN='fake', OPENAI_API_KEY='fake',
                       TELEGRAM_CHAT_ID='-100123', OWNER_TELEGRAM_USER_ID='1',
                       OPENAI_MODEL='fake', DATA_DIR=d)
            with patch.dict(os.environ, env):
                bot = Bot()
                msg = dict(chat={'id':-100123}, **{'from':{'id':2}},
                           message_id=60, date=bot.started, voice={'file_id':'fake'})
                with patch.object(bot, 'download', return_value=b'media'), \
                     patch.object(bot, 'audio_bytes', return_value=b'mp3'), \
                     patch.object(bot, 'transcribe', return_value='Қолип тугамади') as transcribe, \
                     patch.object(bot, 'images', return_value=[(b'jpg','frame')]) as images, \
                     patch.object(bot, 'ai', return_value='Таҳлил') as ai, \
                     patch.object(bot, 'send') as send:
                    bot.handle(msg)
                    images.assert_not_called()
                    self.assertIn('Қолип тугамади', str(ai.call_args))
                    self.assertTrue(any('Овоздан матн' in x.args[0] for x in send.call_args_list))
                    bot.handle(msg)
                    self.assertEqual(transcribe.call_count, 1)
                    self.assertEqual(bot.db.execute('SELECT count(*) FROM inspections').fetchone()[0], 1)
                    self.assertIsNone(bot.db.execute('SELECT reviewed FROM inspections').fetchone()[0])
                    video = {k:v for k,v in msg.items() if k!='voice'}
                    video.update(message_id=61, video={'file_id':'fake'})
                    bot.handle(video)
                    images.assert_called_once_with(video, raw=b'media')
                    self.assertTrue(any(x['type']=='input_image' for x in ai.call_args.args[0]))
                    self.assertIn('Қолип тугамади', str(ai.call_args))
                bot.db.close()

    def test_inspection_review_requires_owner_and_does_not_accept_work(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(TELEGRAM_BOT_TOKEN='fake', OPENAI_API_KEY='fake',
                       TELEGRAM_CHAT_ID='-100123', OWNER_TELEGRAM_USER_ID='1',
                       OPENAI_MODEL='fake', DATA_DIR=d)
            with patch.dict(os.environ, env):
                bot = Bot()
                bot.db.execute('INSERT INTO inspections(source,date,area_report,analysis) VALUES(60,?,?,?)',
                               (bot.started,'6-қават','AI тахмини'))
                bot.db.commit()
                msg = dict(chat={'id':-100123}, **{'from':{'id':2}},
                           message_id=95, date=bot.started, text='/tekshirildi 60')
                with patch.object(bot, 'send') as send:
                    bot.handle(msg)
                    self.assertIsNone(bot.db.execute('SELECT reviewed FROM inspections').fetchone()[0])
                    msg['from']['id'] = 1
                    bot.handle(msg)
                    self.assertEqual(bot.db.execute('SELECT reviewed_by FROM inspections').fetchone()[0], 1)
                    msg.update(message_id=96, text='/nazorat')
                    bot.handle(msg)
                    self.assertIn('иш қабул қилингани эмас', send.call_args.args[0])
                bot.db.close()

    def test_transcription_multipart_and_reserved_analysis_slot(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(TELEGRAM_BOT_TOKEN='fake', OPENAI_API_KEY='fake',
                       TELEGRAM_CHAT_ID='-100123', OWNER_TELEGRAM_USER_ID='1',
                       OPENAI_MODEL='fake', DATA_DIR=d, MAX_DAILY_CALLS='4')
            with patch.dict(os.environ, env):
                bot = Bot()
                with patch('urllib.request.urlopen') as urlopen:
                    urlopen.return_value.__enter__.return_value = io.BytesIO(b'{"text":"speech"}')
                    self.assertEqual(bot.transcribe(b'mp3-data'), 'speech')
                    request = urlopen.call_args.args[0]
                    self.assertIn(b'filename="audio.mp3"', request.data)
                    self.assertIn(b'mp3-data', request.data)
                    self.assertIn(b'gpt-4o-mini-transcribe', request.data)
                    self.assertIn(b'\r\n', request.data)
                    self.assertNotIn(b'fake', request.data)
                    with self.assertRaises(LimitReached):
                        bot.transcribe(b'mp3-data')
                    self.assertEqual(urlopen.call_count, 1)
                    bot.reserve()  # The analysis slot is still available.
                bot.db.close()

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
