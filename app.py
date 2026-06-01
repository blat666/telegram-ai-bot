import asyncio
import datetime
import hashlib
import sqlite3
import os
from threading import Thread
from flask import Flask
import feedparser
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ---------- Настройки ----------
TOKEN = os.environ.get("TOKEN", "8730742431:AAE8qStJGKx1fRkD8AEUd7k98AESixEECCQ")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "3add7899f6c845a992102b61cf46c437")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@ваш_канал")  # Сюда ваш channel_id

# Источники RSS (можете добавлять любые)
RSS_SOURCES = [
    {"name": "Habr AI", "url": "https://habr.com/ru/rss/hub/ai/"},
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/tag/artificial-intelligence/feed/"},
    {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/"},
    {"name": "MIT AI News", "url": "http://news.mit.edu/topic/artificial-intelligence2/feed"},
]

# Интервал проверки в секундах (15 минут = 900 секунд)
CHECK_INTERVAL = 900

# ---------- Flask для Keep-Alive ----------
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "News Aggregator Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app_flask.run(host='0.0.0.0', port=port)

# ---------- Инициализация базы данных ----------
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

# ---------- Парсинг новостей ----------
def fetch_news_from_rss():
    """Собирает новости из всех RSS-источников"""
    all_news = []
    
    for source in RSS_SOURCES:
        try:
            feed = feedparser.parse(source["url"])
            for entry in feed.entries[:3]:  # Берем 3 последние новости из каждого источника
                # Создаём уникальный ID новости (на основе заголовка и ссылки)
                news_id = hashlib.md5(f"{entry.link}{entry.title}".encode()).hexdigest()
                
                # Парсим дату публикации
                published_at = datetime.datetime.now()
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    published_at = datetime.datetime(*entry.published_parsed[:6])
                
                all_news.append({
                    "id": news_id,
                    "title": entry.title,
                    "link": entry.link,
                    "published_at": published_at,
                    "source": source["name"],
                    "summary": extract_summary(entry)
                })
        except Exception as e:
            print(f"Ошибка парсинга {source['name']}: {e}")
    
    # Сортируем по времени публикации (новые сверху)
    all_news.sort(key=lambda x: x["published_at"], reverse=True)
    return all_news

def extract_summary(entry):
    """Извлекает краткое описание из RSS"""
    if hasattr(entry, 'summary'):
        # Очищаем от HTML-тегов
        soup = BeautifulSoup(entry.summary, 'html.parser')
        text = soup.get_text()
        return text[:200] + "..." if len(text) > 200 else text
    return ""

def format_news_for_telegram(news):
    """Форматирует новость для отправки в Telegram"""
    # Текущая дата для заголовка
    today = datetime.datetime.now().strftime('%d.%m.%Y')
    
    message = f"🤖 *{news['source']}*\n"
    message += f"📰 [{news['title']}]({news['link']})\n"
    
    if news['summary']:
        message += f"\n📝 {news['summary']}\n"
    
    message += f"\n🕐 {news['published_at'].strftime('%H:%M')}\n"
    message += "━━━━━━━━━━━━━━━━━━━"
    
    return message

# ---------- Основная логика бота ----------
async def check_and_post(context):
    """Проверяет новые новости и постит их"""
    print(f"[{datetime.datetime.now()}] Проверка новых новостей...")
    
    news_list = fetch_news_from_rss()
    new_count = 0
    
    for news in news_list:
        if not is_news_published(news["id"]):
            # Форматируем и отправляем
            message = format_news_for_telegram(news)
            try:
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=message,
                    parse_mode='Markdown',
                    disable_web_page_preview=False
                )
                save_published_news(
                    news["id"], news["title"], news["link"],
                    news["published_at"], news["source"]
                )
                new_count += 1
                print(f"✅ Опубликовано: {news['title'][:50]}...")
                await asyncio.sleep(1)  # Небольшая пауза между постами
            except Exception as e:
                print(f"❌ Ошибка публикации: {e}")
    
    print(f"📊 Найдено новых новостей: {new_count}")

# ---------- Команды бота ----------
async def start(update: Update, context):
    await update.message.reply_text(
        "🤖 *Новостной агрегатор ИИ*\n\n"
        "Бот автоматически собирает новости из RSS-лент и публикует их в канал.\n\n"
        "📋 /status — статус агрегатора\n"
        "📰 /sources — список источников"
    )

async def status_command(update: Update, context):
    conn = sqlite3.connect('news.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM published_news")
    count = cursor.fetchone()[0]
    conn.close()
    
    await update.message.reply_text(
        f"📊 *Статус агрегатора*\n\n"
        f"📰 Всего опубликовано новостей: {count}\n"
        f"🔗 Источников: {len(RSS_SOURCES)}\n"
        f"⏱ Интервал проверки: {CHECK_INTERVAL // 60} минут\n"
        f"📅 Запущен: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )

async def sources_command(update: Update, context):
    sources_text = "📰 *Источники новостей*\n\n"
    for i, source in enumerate(RSS_SOURCES, 1):
        sources_text += f"{i}. {source['name']}\n"
    
    await update.message.reply_text(sources_text)

# ---------- Запуск ----------
async def main():
    # Инициализируем БД
    init_db()
    
    # Создаём приложение
    application = Application.builder().token(TOKEN).build()
    
    # Добавляем команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("sources", sources_command))
    
    # Настраиваем планировщик
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_and_post, 'interval', seconds=CHECK_INTERVAL, args=[application])
    scheduler.start()
    
    print("✅ Новостной агрегатор запущен!")
    print(f"📡 Проверка RSS каждые {CHECK_INTERVAL // 60} минут")
    print(f"📰 Источников: {len(RSS_SOURCES)}")
    
    # Запускаем Flask в отдельном потоке (для Render)
    flask_thread = Thread(target=run_flask)
    flask_thread.start()
    
    # Запускаем бота
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # Держим бота запущенным
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
