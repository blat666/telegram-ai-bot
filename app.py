import asyncio
import datetime
import hashlib
import os
from threading import Thread
from flask import Flask
import requests
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
NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "3add7899f6c845a992102b61cf46c437")
CHECK_INTERVAL = 300  # 5 минут

# ---------- Русскоязычные юмористические источники ----------
HUMOR_SOURCES = [
    {"name": "IT Юмор", "url": "https://tg.i-c-a.su/rss/@it_ru", "emoji": "😂"},
    {"name": "N+1 (наука с улыбкой)", "url": "https://nplus1.ru/rss", "emoji": "🤣"},
    {"name": "Habr Сарказм", "url": "https://habr.com/ru/rss/hub/sarcasm/", "emoji": "🎭"},
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

# ---------- Получение серьёзных новостей через NewsAPI ----------
def fetch_serious_news():
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": "искусственный интеллект OR нейросети OR AI",
            "language": "ru",
            "sortBy": "publishedAt",
            "apiKey": NEWS_API_KEY,
            "pageSize": 3
        }
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get("status") != "ok":
            print(f"Ошибка NewsAPI: {data.get('message')}")
            return []
        
        articles = data.get("articles", [])
        news_list = []
        
        for article in articles:
            if not article.get("title") or not article.get("url"):
                continue
            news_id = hashlib.md5(f"{article['url']}{article['title']}".encode()).hexdigest()
            published_at = datetime.datetime.now()
            if article.get("publishedAt"):
                try:
                    published_at = datetime.datetime.fromisoformat(article["publishedAt"].replace("Z", "+00:00"))
                except:
                    pass
            
            news_list.append({
                "id": news_id,
                "title": article["title"],
                "link": article["url"],
                "published_at": published_at,
                "source": article.get("source", {}).get("name", "Unknown"),
                "description": article.get("description", "")[:200],
                "type": "serious"
            })
        
        print(f"📰 Серьёзных новостей: {len(news_list)}")
        return news_list
    except Exception as e:
        print(f"❌ Ошибка NewsAPI: {e}")
        return []

# ---------- Получение юмористических постов из RSS ----------
def fetch_humor_news():
    all_posts = []
    for source in HUMOR_SOURCES:
        try:
            print(f"😂 Парсим {source['name']}...")
            feed = feedparser.parse(source["url"])
            for entry in feed.entries[:3]:
                news_id = hashlib.md5(f"{entry.link}{entry.title}".encode()).hexdigest()
                published_at = datetime.datetime.now()
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    published_at = datetime.datetime(*entry.published_parsed[:6])
                
                description = ""
                if hasattr(entry, 'summary'):
                    soup = BeautifulSoup(entry.summary, 'html.parser')
                    description = soup.get_text()[:200]
                elif hasattr(entry, 'description'):
                    soup = BeautifulSoup(entry.description, 'html.parser')
                    description = soup.get_text()[:200]
                
                all_posts.append({
                    "id": news_id,
                    "title": entry.title,
                    "link": entry.link,
                    "published_at": published_at,
                    "source": f"{source['emoji']} {source['name']}",
                    "description": description,
                    "type": "humor"
                })
        except Exception as e:
            print(f"❌ Ошибка парсинга {source['name']}: {e}")
    
    print(f"😂 Юмористических постов: {len(all_posts)}")
    return all_posts

# ---------- Объединённый сбор новостей ----------
def fetch_news():
    serious_news = fetch_serious_news()
    humor_posts = fetch_humor_news()
    
    all_news = serious_news + humor_posts
    
    import random
    random.shuffle(all_news)
    
    print(f"📊 Всего собрано: {len(all_news)}")
    return all_news

def format_news(news):
    if news['type'] == 'humor':
        message = f"🎭 *{news['source']}*\n"
        message += f"😂 [{news['title']}]({news['link']})\n"
        if news['description']:
            message += f"\n💬 {news['description']}\n"
    else:
        message = f"🤖 *{news['source']}*\n"
        message += f"📰 [{news['title']}]({news['link']})\n"
        if news['description']:
            message += f"\n📝 {news['description']}\n"
    
    message += f"\n🕐 {news['published_at'].strftime('%H:%M')}\n"
    message += "━━━━━━━━━━━━━━━━━━━"
    return message

async def check_and_post(context):
    print(f"[{datetime.datetime.now()}] 🔍 Проверка новых постов...")
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
                prefix = "😂" if news['type'] == 'humor' else "📰"
                print(f"{prefix} Опубликовано: {news['title'][:50]}...")
                await asyncio.sleep(2)
            except Exception as e:
                print(f"❌ Ошибка публикации: {e}")
    print(f"📊 Итого новых: {new_count}")

# ---------- Команды ----------
async def start(update: Update, context):
    await update.message.reply_text(
        "🤖 *Новостной агрегатор ИИ с русским юмором*\n\n"
        "📰 Серьёзные новости — NewsAPI\n"
        "😂 Мемы и шутки — русские IT-паблики\n\n"
        "/status — статистика\n"
        "/sources — список источников"
    )

async def status_command(update: Update, context):
    await update.message.reply_text(
        f"📊 *Статистика*\n\n"
        f"📰 Новостей в памяти: {len(published_ids)}\n"
        f"⏱ Интервал: {CHECK_INTERVAL // 60} мин\n"
        f"📡 Серьёзные: NewsAPI\n"
        f"😂 Юмор: {len(HUMOR_SOURCES)} русских источников"
    )

async def sources_command(update: Update, context):
    text = "📰 *Серьёзные источники*\n• NewsAPI (поиск по ИИ)\n\n"
    text += "😂 *Русскоязычные юмористические источники*\n"
    for s in HUMOR_SOURCES:
        text += f"• {s['emoji']} {s['name']}\n"
    await update.message.reply_text(text)

# ---------- Запуск ----------
async def main():
    print("=" * 50)
    print("🚀 ЗАПУСК НОВОСТНОГО АГРЕГАТОРА (NewsAPI + Русский юмор)")
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
