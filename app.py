import asyncio
import datetime
import hashlib
import os
import random
from threading import Thread
from flask import Flask
import requests
import feedparser
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from deep_translator import GoogleTranslator

load_dotenv()

# ---------- Настройки ----------
TOKEN = os.environ.get("TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@ai_diges")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY")
CHECK_INTERVAL = 300  # 5 минут

# ---------- RSS-источники ----------
RSS_SOURCES = [
    {"name": "Habr AI", "url": "https://habr.com/ru/rss/hub/ai/", "lang": "ru"},
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/tag/artificial-intelligence/feed/", "lang": "en"},
    {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/", "lang": "en"},
    {"name": "MIT AI News", "url": "http://news.mit.edu/topic/artificial-intelligence2/feed", "lang": "en"},
    {"name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "lang": "en"},
]

# ---------- Google Translate через deep-translator ----------
async def simple_translate(text, src='en', dest='ru'):
    """Перевод через Google Translate (стабильная версия)"""
    if not text or len(text) < 30:
        return text
    try:
        print(f"🌐 Переводим {len(text)} символов...")
        # Запускаем в отдельном потоке, чтобы не блокировать asyncio
        result = await asyncio.to_thread(
            GoogleTranslator(source=src, target=dest).translate,
            text[:3000]
        )
        print(f"✅ Перевод готов: {result[:50]}...")
        return result
    except Exception as e:
        print(f"❌ Ошибка перевода: {e}")
        return text

# ---------- Flask ----------
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "News Aggregator Bot with Google Translate is running!"

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
def fetch_rss_news():
    all_news = []
    for source in RSS_SOURCES:
        try:
            print(f"📡 Парсим {source['name']}...")
            feed = feedparser.parse(source["url"])
            for entry in feed.entries[:3]:
                news_id = hashlib.md5(f"{entry.link}{entry.title}".encode()).hexdigest()
                
                # Полный текст
                full_text = ""
                if hasattr(entry, 'summary'):
                    soup = BeautifulSoup(entry.summary, 'html.parser')
                    full_text = soup.get_text()
                elif hasattr(entry, 'description'):
                    soup = BeautifulSoup(entry.description, 'html.parser')
                    full_text = soup.get_text()
                
                # Картинка (если есть)
                image_url = ""
                if hasattr(entry, 'media_content') and entry.media_content:
                    image_url = entry.media_content[0].get('url', '')
                
                all_news.append({
                    "id": news_id,
                    "title": entry.title,
                    "full_text": full_text[:1500],
                    "link": entry.link,
                    "image_url": image_url,
                    "published_at": datetime.datetime.now(),
                    "source": source["name"],
                    "lang": source.get("lang", "en")
                })
        except Exception as e:
            print(f"❌ Ошибка {source['name']}: {e}")
    
    print(f"📰 Собрано новостей RSS: {len(all_news)}")
    return all_news

# ---------- NewsAPI (как резерв) ----------
def fetch_newsapi():
    if not NEWS_API_KEY:
        return []
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": "artificial intelligence OR AI OR нейросети",
            "language": "en",
            "sortBy": "publishedAt",
            "apiKey": NEWS_API_KEY,
            "pageSize": 2
        }
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if data.get("status") != "ok":
            return []
        news_list = []
        for article in data.get("articles", []):
            if not article.get("title"):
                continue
            news_id = hashlib.md5(f"{article['url']}{article['title']}".encode()).hexdigest()
            news_list.append({
                "id": news_id,
                "title": article["title"],
                "full_text": article.get("description", ""),
                "link": article["url"],
                "image_url": article.get("urlToImage", ""),
                "published_at": datetime.datetime.now(),
                "source": article.get("source", {}).get("name", "NewsAPI"),
                "lang": "en"
            })
        return news_list
    except Exception as e:
        print(f"❌ Ошибка NewsAPI: {e}")
        return []

# ---------- Форматирование с переводом ----------
async def format_news(news):
    # Переводим на русский если нужно
    if news["lang"] == "en" and news["full_text"] and len(news["full_text"]) > 30:
        processed_text = await simple_translate(news["full_text"])
    elif news["full_text"]:
        processed_text = news["full_text"]
    else:
        processed_text = news["title"]
    
    # Обрезаем до 800 символов, завершая предложение
    if len(processed_text) > 800:
        last_dot = processed_text[:800].rfind('.')
        if last_dot > 0:
            processed_text = processed_text[:last_dot + 1]
    
    # Формируем сообщение
    message = f"🤖 *{news['source']}*\n\n"
    message += f"{processed_text}\n\n"
    message += f"🔗 [Читать полностью]({news['link']})\n"
    message += f"\n🕐 {news['published_at'].strftime('%H:%M')}\n"
    message += "━━━━━━━━━━━━━━━━━━━"
    
    return message, news.get("image_url", "")

async def check_and_post(context):
    print(f"[{datetime.datetime.now()}] 🔍 Проверка новых новостей...")
    
    rss_news = fetch_rss_news()
    newsapi_news = fetch_newsapi()
    all_news = rss_news + newsapi_news
    random.shuffle(all_news)
    
    new_count = 0
    for news in all_news:
        if not is_published(news["id"]):
            message, image_url = await format_news(news)
            try:
                if image_url:
                    await context.bot.send_photo(
                        chat_id=CHANNEL_ID,
                        photo=image_url,
                        caption=message,
                        parse_mode='Markdown'
                    )
                else:
                    await context.bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=message,
                        parse_mode='Markdown',
                        disable_web_page_preview=False
                    )
                save_published(news["id"])
                new_count += 1
                print(f"✅ Опубликовано: {news['title'][:50]}...")
                await asyncio.sleep(3)
            except Exception as e:
                print(f"❌ Ошибка публикации: {e}")
    
    print(f"📊 Итого новых: {new_count}")

# ---------- Команды ----------
async def start(update: Update, context):
    await update.message.reply_text(
        "🤖 *Новостной агрегатор с переводом*\n\n"
        "📰 Парсинг RSS-источников\n"
        "🌐 Google Translate (стабильный)\n"
        "🔗 Ссылка на источник\n"
        "🖼 Картинки при наличии\n\n"
        "/status — статистика\n"
        "/sources — источники"
    )

async def status_command(update: Update, context):
    await update.message.reply_text(
        f"📊 *Статистика*\n\n"
        f"📰 Новостей в памяти: {len(published_ids)}\n"
        f"⏱ Интервал: {CHECK_INTERVAL // 60} мин\n"
        f"📡 RSS-источников: {len(RSS_SOURCES)}\n"
        f"🌐 Перевод: Google Translate\n"
        f"🖼 Картинки: ✅"
    )

async def sources_command(update: Update, context):
    text = "📰 *RSS-источники*\n"
    for s in RSS_SOURCES:
        lang_emoji = "🇷🇺" if s.get("lang") == "ru" else "🇬🇧"
        text += f"• {lang_emoji} {s['name']}\n"
    if NEWS_API_KEY:
        text += "\n📡 NewsAPI (резерв)"
    await update.message.reply_text(text)

# ---------- Запуск ----------
async def main():
    print("=" * 50)
    print("🚀 ЗАПУСК НОВОСТНОГО АГРЕГАТОРА (deep-translator)")
    print("=" * 50)
    print(f"✅ Канал: {CHANNEL_ID}")
    print(f"📡 RSS-источников: {len(RSS_SOURCES)}")
    print(f"🌐 Перевод: Google Translate (deep-translator)")
    
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("sources", sources_command))
    
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_and_post, 'interval', seconds=CHECK_INTERVAL, args=[application])
    scheduler.start()
    print(f"✅ Планировщик: {CHECK_INTERVAL // 60} минут")
    
    asyncio.create_task(check_and_post(application))
    
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
