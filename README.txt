URGENCH QURILISH BOTI — O'RNATISH PAKETI
Holat: kod tekshirilgan; hostingda Telegram buyruqlari ishladi, AI natijasi hali tasdiqlanmagan.
Bot: @Urgench10QavatNazorat_bot. Maxfiy kalitlar paketga kiritilmagan.

Imkoniyatlar
- Guruh yangi matnlarini SQLite jurnalga saqlash.
- Egasi rasmlarga/video xabarlariga Reply qilib /tahlil yuborishi mumkin.
- Video: 19 MB va 3 daqiqagacha, 6 ta teng taqsimlangan kadr. Audio tekshirilmaydi.
- Egasi /status orqali oxirgi 7 kun qaydlaridan status oladi.
- Yangi media avtomatik tahlil qilinadi; eski AUTO_ANALYZE sozlamasi ishlatilmaydi.
- Oddiy matnlar 5 daqiqalik to'plamda AI kuzatuvidan o'tadi; bayonotlar tekshirilmagan deb belgilanadi.
- Kunlik hisobot 20:00, haftalik juma 19:00 (Asia/Tashkent), buyruqsiz yuboriladi.
- Muddati o'tgan ochiq vazifalar har kuni 09:00 dan keyin eslatiladi.
- /vazifa YYYY-MM-DD | mas'ul | ish — faqat egasi tasdiqlagan reja.
- /vazifalar — ro'yxat; /bajarildi ID — egasi bajarilganini tasdiqlaydi.
- /bugun — 1 kunlik hisobot; /holat — AI muvaffaqiyati, xato va kunlik sarflangan so'rovlar.
- AI tavsiyasi vazifa yaratmaydi va bajarilganligini tasdiqlamaydi.
- Har kuni Toshkent sanasi bo'yicha maksimum 10 AI urinish (o'zgartirish mumkin).
  Shundan 2 so'rov hisobotlar uchun saqlanadi. Limitda xabarlar qayd qilinadi,
  matn tahlili navbatda qoladi, yangi media AI tahlili o'tkazib yuborilishi mumkin.
Bu pul bo'yicha qat'iy limit emas: tokenlar va model narxi xarajatni belgilaydi.
- Faqat TELEGRAM_CHAT_ID bilan ko'rsatilgan bitta guruhni kuzatadi.
- baseline.json tasdiqlangan qiymatlar uchun o'zgarmas manba: bot uni yozmaydi.
Hozir tarixiy raqamlar import qilinmagan. AI tahlili tasdiqlangan ish hisoblanmaydi.

Ishga tushirish (serverga o'rnatuvchi uchun)
1. Doim ishlaydigan Docker server yoki container worker ajrating.
2. .env.example nomlarini hosting secrets/variables bo'limida to'ldiring.
   OPENAI_MODEL — hisobda mavjud, rasmlarni qabul qiladigan Responses modeli.
   Haqiqiy kalitlarni GitHub, chat, log yoki skrinshotda ko'rsatmang.
3. Guruh ID va egasi user IDni Telegram getUpdates natijasidagi message.chat.id
   va message.from.iddan server tomonda oling. Token URLni chatga yubormang.
4. BotFather /setprivacy -> Disable. Zarur bo'lsa botni guruhdan chiqarib qayta qo'shing.
5. Bitta instance, doimiy /data volume. Bir xil token bilan boshqa polling/webhook ishlamasin.
6. docker build -t urgench-bot .
7. docker run -d --restart unless-stopped --env-file .env -v urgench-data:/data urgench-bot
8. Guruhda /start -> javobni tekshiring. Bir rasmdan /tahlil, keyin /status sinovi.
   Kalit/model/billing xatosi bo'lsa natija chiqmaydi; haqiqiy test o'tmaguncha
   ishlayapti deb hisoblamang. Kalitning amal qilish muddatini tekshiring.

Cheklovlar va ma'lumotlar
- Bu chatning haftalik avtomatizatsiyasi bilan Telegram bot ulanmagan.
- Telegram hisobotlarini botning o'zi yuboradi; server o'chiq bo'lsa yubora olmaydi.
  Shu kun ichida qayta ishga tushsa o'tgan hisobot vaqtidan keyin bir marta yuboradi.
  Muvaffaqiyatli yuborish holati SQLite'da saqlanadi; uzilish aynan yuborish vaqtida
  yuz bersa hisobot takrorlanishi mumkin.
- Bot oldingi guruh tarixini to'liq o'qimaydi; faqat kelgan updatesni saqlaydi.
- Albomdagi har bir rasm alohida tahlil qilinadi. PNG hujjatlar hozir qo'llanmaydi;
  Telegram photo yoki JPEG hujjat yuboring.
- Oxirgi 120 qayd statusga kiritiladi; agar ko'p bo'lsa hisobot to'liq emasligini aytadi.
- Eski qolib ketgan /tahlil va /status buyruqlari ishga tushganda bajarilishi mumkin.
- AI chaqiruvi vaqtida server uzilsa takroriy xarajat/javob yuz berishi mumkin.
  API xatoli update qayta avtomatik bajarilmaydi; /tahlilni qayta yuboring.
- Kundalik cap katta xarajatni kamaytiradi, aniq dollar budjetini kafolatlamaydi.
- Maxfiylik: guruhga qaysi ma'lumotlar qayd qilinishi va AIga yuborilishini tushuntiring.
  Matnlar doimiy volume'da qoladi; raw media vaqtinchalik olinib o'chiriladi.
- Rasm/video beton mustahkamligi, yashirin armatura yoki bino xavfsizligini tasdiqlamaydi.
  Muhandislik qarori tegishli ishchi loyiha, sinov va mutaxassis xulosasiga bog'liq.

Manbalar (2026-10-06 tekshirildi)
https://core.telegram.org/bots/api
https://core.telegram.org/bots/features#privacy-mode
https://developers.openai.com/api/docs/guides/images-vision
https://developers.openai.com/api/docs/quickstart

Sinovlar: test_bot.py — buyruq/caption, kunlik limit va hisobot zaxirasi,
baseline o'zgarmasligi, guruh/egasi izolyatsiyasi, vazifalar, sana tekshiruvi,
hisobot takrorlanmasligi, qayta ishga tushishda saqlash, matn navbati.
