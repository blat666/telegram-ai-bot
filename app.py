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
from openai import OpenAI

load_dotenv()

# ---------- Настройки ----------
TOKEN = os.environ.get("TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@ai_diges")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
CHECK_INTERVAL = 300  # 5 минут

# ---------- RSS-источники (можно любые, хоть английские) ----------
RSS_SOURCES = [
    {"name": "Habr AI", "url": "https://habr.com/ru/rss/hub/ai/", "lang": "ru"},
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/tag/artificial-intelligence/feed/", "lang": "en"},
    {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/", "lang": "en"},
    {"name": "MIT AI News", "url": "http://news.mit.edu/topic/artificial-intelligence2/feed", "lang": "en"},
    {"name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "lang": "en"},
]

# ---------- Настройки AI ----------
if OPENROUTER_API_KEY:
    openai_client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )
else:
    openai_client = None

# ---------- Flask ----------
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "News Aggregator Bot with AI Translation is running!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app_flask.run(host='0.0.0.0', port=port)

# ---------- Хранилище ID новостей ----------
published_ids = set()

def is_published(news_id):
    return news_id in published_ids

def save_published(news_id):
    published_ids.add(news_id)

# ---------- AI: перевод + рерайт ----------
async def translate_and_rewrite(text, source_lang="en"):
    """Переводит с английского на русский и делает рерайт"""
    if not text or len(text) < 30 or not openai_client:
        return text
    
    if source_lang == "ru":
        prompt = f"Перепиши этот текст короче и интереснее для Telegram-канала об ИИ. Сохрани смысл, добавь эмодзи где уместно. Не добавляй ссылки. Текст:\n\n{text}"
    else:
        prompt = f"Переведи этот текст с английского на русский и перепиши его в стиле Telegram-канала об ИИ. Сделай короче, добавь эмодзи. Сохрани смысл. Текст:\n\n{text}"
    
    try:
        response = openai_client.chat.completions.create(
            model="google/gemini-2.0-flash-exp:free",
            messages=[
                {"role": "system", "content": "Ты — редактор новостного канала об искусственном интеллекте. Твоя задача: переводить и переписывать новости так, чтобы они были короткими, интересными и понятными. Добавляй эмодзи. Не меняй смысл."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=400
        )
        result = response.choices[0].message.content
        return result[:500]
    except Exception as e:
        print(f"❌ Ошибка AI: {e}")
        return text

# ---------- Парсинг RSS ----------
def fetch_rss_news():
    all_news = []
    for source in RSS_SOURCES:
        try:
            print(f"📡 Парсим {source['name']}...")
            feed = feedparser.parse(source["url"])
            for entry in feed.entries[:3]:
                news_id = hashlib.md5(f"{entry.link}{entry.title}".encode()).hexdigest()
                
                # Оригинальный заголовок и описание
                title = entry.title
                summary = ""
                if hasattr(entry, 'summary'):
                    soup = BeautifulSoup(entry.summary, 'html.parser')
                    summary = soup.get_text()[:500]
                elif hasattr(entry, 'description'):
                    soup = BeautifulSoup(entry.description, 'html.parser')
                    summary = soup.get_text()[:500]
                
                all_news.append({
                    "id": news_id,
                    "original_title": title,
                    "original_summary": summary,
                    "link": entry.link,
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
            "pageSize": 3
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
                "original_title": article["title"],
                "original_summary": article.get("description", ""),
                "link": article["url"],
                "published_at": datetime.datetime.now(),
                "source": article.get("source", {}).get("name", "NewsAPI"),
                "lang": "en"
            })
        return news_list
    except Exception as e:
        print(f"❌ Ошибка NewsAPI: {e}")
        return []

# ---------- Форматирование с AI ----------
async def format_news(news):
    # Переводим и переписываем заголовок
    processed_title = await translate_and_rewrite(news["original_title"], news["lang"])
    
    # Переводим и переписываем описание (если есть)
    processed_summary = ""
    if news["original_summary"] and len(news["original_summary"]) > 30:
        processed_summary = await translate_and_rewrite(news["original_summary"], news["lang"])
    
    # Собираем сообщение
    message = f"🤖 *{news['source']}*\n"
    message += f"📌 {processed_title}\n"
    if processed_summary:
        message += f"\n📝 {processed_summary}\n"
    message += f"\n🕐 {news['published_at'].strftime('%H:%M')}\n"
    message += "━━━━━━━━━━━━━━━━━━━"
    return message

async def check_and_post(context):
    print(f"[{datetime.datetime.now()}] 🔍 Проверка новых новостей...")
    
    # Собираем новости из всех источников
    rss_news = fetch_rss_news()
    newsapi_news = fetch_newsapi()
    all_news = rss_news + newsapi_news
    random.shuffle(all_news)
    
    new_count = 0
    for news in all_news:
        if not is_published(news["id"]):
            message = await format_news(news)
            try:
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=message,
                    parse_mode='Markdown',
                    disable_web_page_preview=False
                )
                save_published(news["id"])
                new_count += 1
                print(f"✅ Опубликовано: {news['original_title'][:50]}...")
                await asyncio.sleep(3)  # Пауза между постами
            except Exception as e:
                print(f"❌ Ошибка публикации: {e}")
    
    print(f"📊 Итого новых: {new_count}")

# ---------- Команды ----------
async def start(update: Update, context):
    await update.message.reply_text(
        "🤖 *Новостной агрегатор с AI-переводом*\n\n"
        "📰 Парсинг любых RSS-источников\n"
        "🌐 Автоматический перевод с английского\n"
        "✍️ AI-рерайт для уникальности\n\n"
        "/status — статистика\n"
        "/sources — источники"
    )

async def status_command(update: Update, context):
    ai_status = "✅ включён" if openai_client else "❌ отключён"
    await update.message.reply_text(
        f"📊 *Статистика*\n\n"
        f"📰 Новостей в памяти: {len(published_ids)}\n"
        f"⏱ Интервал: {CHECK_INTERVAL // 60} мин\n"
        f"📡 RSS-источников: {len(RSS_SOURCES)}\n"
        f"✍️ AI-перевод+рерайт: {ai_status}"
    )

async def sources_command(update: Update, context):
    text = "📰 *RSS-источники*\n"
    for s in RSS_SOURCES:
        lang_emoji = "🇷🇺" if s.get("lang") == "ru" else "🇬🇧"
        text += f"• {lang_emoji} {s['name']}\n"
    await update.message.reply_text(text)

# ---------- Запуск ----------
async def main():
    print("=" * 50)
    print("🚀 ЗАПУСК НОВОСТНОГО АГРЕГАТОРА (AI Translator)")
    print("=" * 50)
    print(f"✅ Канал: {CHANNEL_ID}")
    print(f"📡 RSS-источников: {len(RSS_SOURCES)}")
    print(f"✍️ AI-рерайт: {'включён' if openai_client else 'отключён'}")
    
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("sources", sources_command))
    
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_and_post, 'interval', seconds=CHECK_INTERVAL, args=[application])
    scheduler.start()
    print(f"✅ Планировщик: {CHECK_INTERVAL // 60} минут")
    
    # Немедленный запуск
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
