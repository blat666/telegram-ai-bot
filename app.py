import asyncio
import datetime
import hashlib
import sqlite3
import os
from threading import Thread
from flask import Flask
import feedparser
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

# ---------- Настройки ----------
TOKEN = os.environ.get("TOKEN", "8730742431:AAE8qStJGKx1fRkD8AEUd7k98AESixEECCQ")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@ai_diges")
CHECK_INTERVAL = 900  # 15 минут

# ---------- Русскоязычные источники RSS ----------
RSS_SOURCES = [
    {"name": "Habr AI", "url": "https://habr.com/ru/rss/hub/ai/"},
    {"name": "3DNews AI", "url": "https://3dnews.ru/news/search/искусственный+интеллект/rss/"},
    {"name": "VC.ru AI", "url": "https://vc.ru/tag/ai/rss"},
    {"name": "Tproger AI", "url": "https://tproger.ru/tag/ai/feed"},
    {"name": "IXBT AI", "url": "https://www.ixbt.com/export/news_ai.xml"},
]

# ---------- Flask ----------
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "News Aggregator Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app_flask.run(host='0.0.0.0', port=port)

# ---------- База данных ----------
def init_db():
    conn = sqlite3.connect('news.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS published_news (
            id TEXT PRIMARY KEY,
            title TEXT,
            link TEXT,
            published_at TIMESTAMP,
            source TEXT
        )
    ''')
    conn.commit()
    conn.close()
    print("✅ База данных инициализирована")

def is_news_published(news_id):
    conn = sqlite3.connect('news.db')
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM published_news WHERE id = ?", (news_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def save_published_news(news_id, title, link, published_at, source):
    conn = sqlite3.connect('news.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO published_news (id, title, link, published_at, source)
        VALUES (?, ?, ?, ?, ?)
    ''', (news_id, title, link, published_at, source))
    conn.commit()
    conn.close()

# ---------- Парсинг RSS ----------
def fetch_news_from_rss():
    all_news = []
    for source in RSS_SOURCES:
        try:
            print(f"📡 Парсим {source['name']}...")
            feed = feedparser.parse(source["url"])
            for entry in feed.entries[:3]:
                news_id = hashlib.md5(f"{entry.link}{entry.title}".encode()).hexdigest()
                published_at = datetime.datetime.now()
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    published_at = datetime.datetime(*entry.published_parsed[:6])
                summary = ""
                if hasattr(entry, 'summary'):
                    soup = BeautifulSoup(entry.summary, 'html.parser')
                    summary = soup.get_text()[:200]
                all_news.append({
                    "id": news_id,
                    "title": entry.title,
                    "link": entry.link,
                    "published_at": published_at,
                    "source": source["name"],
                    "summary": summary
                })
        except Exception as e:
            print(f"❌ Ошибка {source['name']}: {e}")
    all_news.sort(key=lambda x: x["published_at"], reverse=True)
    print(f"📰 Собрано новостей: {len(all_news)}")
    return all_news

def format_news_for_telegram(news):
    message = f"🤖 *{news['source']}*\n"
    message += f"📰 [{news['title']}]({news['link']})\n"
    if news['summary']:
        message += f"\n📝 {news['summary']}\n"
    message += f"\n🕐 {news['published_at'].strftime('%H:%M')}\n"
    message += "━━━━━━━━━━━━━━━━━━━"
    return message

# ---------- Публикация ----------
async def check_and_post(context):
    print(f"[{datetime.datetime.now()}] 🔍 Проверка новых новостей...")
    news_list = fetch_news_from_rss()
    new_count = 0
    for news in news_list:
        if not is_news_published(news["id"]):
            message = format_news_for_telegram(news)
            try:
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=message,
                    parse_mode='Markdown',
                    disable_web_page_preview=False
                )
                save_published_news(news["id"], news["title"], news["link"], news["published_at"], news["source"])
                new_count += 1
                print(f"✅ Опубликовано: {news['title'][:50]}...")
                await asyncio.sleep(1)
            except Exception as e:
                print(f"❌ Ошибка публикации: {e}")
    print(f"📊 Итого новых новостей: {new_count}")

# ---------- Команды Telegram ----------
async def start(update: Update, context):
    await update.message.reply_text(
        "🤖 *Новостной агрегатор ИИ*\n\n"
        "/status — статус\n"
        "/sources — источники\n"
        "/help — помощь"
    )

async def status_command(update: Update, context):
    conn = sqlite3.connect('news.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM published_news")
    count = cursor.fetchone()[0]
    conn.close()
    await update.message.reply_text(
        f"📊 *Статус*\n\n"
        f"📰 Новостей: {count}\n"
        f"🔗 Источников: {len(RSS_SOURCES)}\n"
        f"⏱ Интервал: {CHECK_INTERVAL // 60} мин"
    )

async def sources_command(update: Update, context):
    text = "📰 *Источники*\n\n"
    for i, s in enumerate(RSS_SOURCES, 1):
        text += f"{i}. {s['name']}\n"
    await update.message.reply_text(text)

async def help_command(update: Update, context):
    await update.message.reply_text("/start\n/status\n/sources")

# ---------- Запуск ----------
async def main():
    print("=" * 50)
    print("🚀 ЗАПУСК НОВОСТНОГО АГРЕГАТОРА")
    print("=" * 50)
    print(f"✅ Канал: {CHANNEL_ID}")
    init_db()
    
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("sources", sources_command))
    application.add_handler(CommandHandler("help", help_command))
    
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_and_post, 'interval', seconds=CHECK_INTERVAL, args=[application])
    scheduler.start()
    print(f"✅ Планировщик: {CHECK_INTERVAL // 60} минут")
    print(f"📡 Источников: {len(RSS_SOURCES)}")
    
    flask_thread = Thread(target=run_flask)
    flask_thread.start()
    print("✅ Flask запущен")
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    print("=" * 50)
    print("✅ БОТ УСПЕШНО ЗАПУЩЕН!")
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
