import asyncio
import datetime
import os
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

# ---------- Настройки ----------
TOKEN = os.environ.get("TOKEN", "8730742431:AAE77Bk8ji-OUCxFiiCqezFZGGdBak33bfY")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@ai_diges")
CHECK_INTERVAL = 60  # 1 минута

# ---------- Flask для Keep-Alive ----------
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "News Aggregator Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app_flask.run(host='0.0.0.0', port=port)

# ---------- Счётчик тестовых новостей ----------
counter = 0

# ---------- Функция публикации тестовых новостей ----------
async def post_test_news(context):
    global counter
    counter += 1
    now = datetime.datetime.now().strftime("%H:%M:%S")
    
    message = f"""🤖 *ТЕСТОВАЯ НОВОСТЬ #{counter}*
    
🕐 Время: {now}

✅ Если вы видите это сообщение — бот успешно публикует посты в канал!

📡 Интервал: {CHECK_INTERVAL} секунд
🔗 Источник: Тестовый режим

━━━━━━━━━━━━━━━━━━━"""
    
    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            parse_mode='Markdown'
        )
        print(f"[{now}] ✅ Опубликована тестовая новость #{counter}")
    except Exception as e:
        print(f"❌ Ошибка публикации: {e}")

# ---------- Команды бота ----------
async def start(update: Update, context):
    await update.message.reply_text(
        "🤖 *Тестовый режим*\n\n"
        "Бот публикует тестовые новости каждую минуту.\n"
        "/status — статистика"
    )

async def status_command(update: Update, context):
    await update.message.reply_text(
        f"📊 *Статус тестового режима*\n\n"
        f"📰 Опубликовано тестов: {counter}\n"
        f"⏱ Интервал: {CHECK_INTERVAL} сек\n"
        f"📡 Режим: тестовый"
    )

# ---------- Запуск ----------
async def main():
    print("=" * 50)
    print("🚀 ЗАПУСК ТЕСТОВОГО РЕЖИМА")
    print("=" * 50)
    print(f"✅ Канал: {CHANNEL_ID}")
    print(f"⏱ Интервал: {CHECK_INTERVAL} секунд")
    
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status_command))
    
    scheduler = AsyncIOScheduler()
    scheduler.add_job(post_test_news, 'interval', seconds=CHECK_INTERVAL, args=[application])
    scheduler.start()
    print("✅ Планировщик запущен")
    
    flask_thread = Thread(target=run_flask)
    flask_thread.start()
    print("✅ Flask запущен")
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    print("=" * 50)
    print("✅ ТЕСТОВЫЙ БОТ ЗАПУЩЕН!")
    print("📨 Тестовые новости будут приходить каждую минуту")
    print("=" * 50)
    
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
