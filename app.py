import asyncio
import datetime
import hashlib
import os
from threading import Thread
from flask import Flask
import feedparser
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

# ---------- Настройки ----------
TOKEN = os.environ.get("TOKEN", "8730742431:AAE77Bk8ji-OUCxFiiCqezFZGGdBak33bfY")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@ai_diges")
CHECK_INTERVAL = 900  # 15 минут

# ---------- RSS источники (5 серьёзных + 2 юмористических) ----------
RSS_SOURCES = [
    # Серьёзные
    {"name": "Habr AI", "url": "https://habr.com/ru/rss/hub/ai/"},
    {"name": "Tproger AI", "url": "https://tproger.ru/tag/ai/feed"},
    {"name": "IXBT AI", "url": "https://www.ixbt.com/export/news_ai.xml"},
    {"name": "3DNews AI", "url": "https://3dnews.ru/news/search/искусственный+интеллект/rss/"},
    {"name": "VC.ru AI", "url": "https://vc.ru/tag/ai/rss"},
    # Юмористические
    {"name": "AI Memes Reddit", "url": "https://www.reddit.com/r/ai_memes/.rss"},
    {"name": "ProgrammerHumor AI", "url": "https://www.reddit.com/r/ProgrammerHumor/search.rss?q=ai&restrict_sr=on&sort=hot"},
]

# ---------- Flask ----------
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "News Aggregator Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app_flask.run(host='0.0.0.0', port=port)

# ---------- Хранилище ID новостей ----------
published_ids = set()

def is_published(news_id):
    return news_id in published_ids

def save_published(news_id):
    published_ids.add(news_id)

# ---------- Парсинг RSS ----------
def fetch_news():
    all_news = []
    for source in RSS_SOURCES:
        try:
            print(f"📡 Парсим {source['name']}...")
            feed = feedparser.parse(source["url"])
            for entry in feed.entries[:5]:
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

def format_news(news):
    message = f"🤖 *{news['source']}*\n"
    message += f"📰 [{news['title']}]({news['link']})\n"
    if news['summary']:
        message += f"\n📝 {news['summary']}\n"
    message += f"\n🕐 {news['published_at'].strftime('%H:%M')}\n"
    message += "━━━━━━━━━━━━━━━━━━━"
    return message

async def check_and_post(context):
    print(f"[{datetime.datetime.now()}] 🔍 Проверка новых новостей...")
    news_list = fetch_news()
    new_count = 0
    for news in news_list:
        if not is_published(news["id"]):
            message = format_news(news)
            try:
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=message,
                    parse_mode='Markdown',
                    disable_web_page_preview=False
                )
                save_published(news["id"])
                new_count += 1
                print(f"✅ Опубликовано: {news['title'][:50]}...")
                await asyncio.sleep(2)
            except Exception as e:
                print(f"❌ Ошибка публикации: {e}")
    print(f"📊 Итого новых: {new_count}")

# ---------- Команды ----------
async def start(update: Update, context):
    await update.message.reply_text("🤖 Новостной агрегатор ИИ\n/status — статистика\n/sources — источники")

async def status_command(update: Update, context):
    await update.message.reply_text(f"📊 Новостей в памяти: {len(published_ids)}\n🔗 Источников: {len(RSS_SOURCES)}\n⏱ Интервал: {CHECK_INTERVAL // 60} мин")

async def sources_command(update: Update, context):
    text = "📰 Источники:\n"
    for i, s in enumerate(RSS_SOURCES, 1):
        emoji = "😄" if "Memes" in s['name'] or "Humor" in s['name'] else "📰"
        text += f"{i}. {emoji} {s['name']}\n"
    await update.message.reply_text(text)

# ---------- Запуск ----------
async def main():
    print("=" * 50)
    print("🚀 ЗАПУСК НОВОСТНОГО АГРЕГАТОРА")
    print("=" * 50)
    print(f"✅ Канал: {CHANNEL_ID}")
    
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("sources", sources_command))
    
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_and_post, 'interval', seconds=CHECK_INTERVAL, args=[application])
    scheduler.start()
    print(f"✅ Планировщик: {CHECK_INTERVAL // 60} минут")
    
    flask_thread = Thread(target=run_flask)
    flask_thread.start()
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    print("✅ БОТ ЗАПУЩЕН!")
    
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
