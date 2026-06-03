import asyncio
import datetime
import hashlib
import os
import random
from threading import Thread
from flask import Flask
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.network.connection.tcpabridged import ConnectionTcpAbridged
from openai import OpenAI

load_dotenv()

# ---------- Настройки ----------
TOKEN = os.environ.get("TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@ai_diges")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY")
API_ID = int(os.environ.get("API_ID", 31563391))
API_HASH = os.environ.get("API_HASH", '76bc8833471380628c81fbba9d6e8014')
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
CHECK_INTERVAL = 300  # 5 минут

# ---------- Telegram-каналы для парсинга ----------
SOURCE_CHANNELS = [
    "@it_ru",
    "@rbc_news",
    "@meduzalive",
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
    return "News Aggregator Bot with AI Rewrite is running!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app_flask.run(host='0.0.0.0', port=port)

# ---------- Хранилище ID новостей ----------
published_ids = set()

def is_published(news_id):
    return news_id in published_ids

def save_published(news_id):
    published_ids.add(news_id)

# ---------- AI-рерайт ----------
async def rewrite_text(text):
    if not text or len(text) < 50 or not openai_client:
        return text
    try:
        response = openai_client.chat.completions.create(
            model="google/gemini-2.0-flash-exp:free",
            messages=[
                {"role": "system", "content": "Ты — редактор новостного канала. Перепиши этот текст короче и интереснее, сохранив смысл. Убери воду, сделай стиль живым. Не добавляй ссылки. Ответь только переписанным текстом."},
                {"role": "user", "content": text}
            ],
            temperature=0.7,
            max_tokens=500
        )
        return response.choices[0].message.content[:400]
    except Exception as e:
        print(f"❌ Ошибка AI: {e}")
        return text

# ---------- Парсинг каналов через Telethon ----------
async def fetch_from_channels():
    if not API_ID or not API_HASH:
        return []
    
    all_posts = []
    try:
        async with TelegramClient('session', API_ID, API_HASH, connection=ConnectionTcpAbridged) as client:
            for channel_name in SOURCE_CHANNELS:
                try:
                    print(f"📡 Парсим канал {channel_name}...")
                    channel = await client.get_entity(channel_name)
                    async for message in client.iter_messages(channel, limit=2):
                        if message.text and len(message.text) > 50:
                            news_id = hashlib.md5(f"{channel_name}{message.id}{message.text[:50]}".encode()).hexdigest()
                            all_posts.append({
                                "id": news_id,
                                "title": message.text[:100],
                                "full_text": message.text,
                                "link": f"https://t.me/{channel_name.replace('@', '')}/{message.id}",
                                "published_at": message.date,
                                "source": channel_name,
                                "type": "channel"
                            })
                except Exception as e:
                    print(f"❌ Ошибка канала {channel_name}: {e}")
    except Exception as e:
        print(f"❌ Ошибка Telethon: {e}")
    
    print(f"📊 Из каналов собрано: {len(all_posts)}")
    return all_posts

# ---------- NewsAPI ----------
def fetch_serious_news():
    if not NEWS_API_KEY:
        return []
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
                "published_at": datetime.datetime.now(),
                "source": article.get("source", {}).get("name", "Unknown"),
                "type": "newsapi"
            })
        return news_list
    except Exception as e:
        print(f"❌ Ошибка NewsAPI: {e}")
        return []

# ---------- Объединённый сбор ----------
async def fetch_all_news():
    serious = fetch_serious_news()
    channels = await fetch_from_channels()
    all_news = serious + channels
    random.shuffle(all_news)
    print(f"📊 Всего собрано: {len(all_news)}")
    return all_news

# ---------- Форматирование ----------
async def format_news(news):
    if news['type'] == 'channel' and news.get('full_text'):
        text = await rewrite_text(news['full_text'])
        if not text or len(text) < 30:
            text = news['title']
    else:
        text = news['title']
    
    emoji = "🔥" if news['type'] == 'channel' else "🤖"
    message = f"{emoji} *{news['source']}*\n"
    message += f"📰 {text}\n"
    message += f"\n🔗 [Читать полностью]({news['link']})\n"
    message += f"\n🕐 {news['published_at'].strftime('%H:%M') if hasattr(news['published_at'], 'strftime') else datetime.datetime.now().strftime('%H:%M')}\n"
    message += "━━━━━━━━━━━━━━━━━━━"
    return message

async def check_and_post(context):
    print(f"[{datetime.datetime.now()}] 🔍 Проверка новых постов...")
    news_list = await fetch_all_news()
    new_count = 0
    for news in news_list:
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
                print(f"✅ Опубликовано: {news['title'][:50]}...")
                await asyncio.sleep(2)
            except Exception as e:
                print(f"❌ Ошибка публикации: {e}")
    print(f"📊 Итого новых: {new_count}")

# ---------- Команды ----------
async def start(update: Update, context):
    await update.message.reply_text(
        "🤖 *Новостной агрегатор с AI-рерайтом*\n\n"
        "📰 NewsAPI\n🔥 Telegram-каналы\n✍️ AI-рерайт\n\n"
        "/status — статистика\n/sources — источники"
    )

async def status_command(update: Update, context):
    await update.message.reply_text(
        f"📊 *Статистика*\n\n"
        f"📰 Новостей в памяти: {len(published_ids)}\n"
        f"⏱ Интервал: {CHECK_INTERVAL // 60} мин\n"
        f"🔥 Каналов: {len(SOURCE_CHANNELS)}\n"
        f"✍️ AI-рерайт: {'включён' if openai_client else 'отключён'}"
    )

async def sources_command(update: Update, context):
    text = "📰 NewsAPI\n\n🔥 Telegram-каналы:\n"
    for ch in SOURCE_CHANNELS:
        text += f"• {ch}\n"
    await update.message.reply_text(text)

# ---------- Запуск ----------
async def main():
    print("=" * 50)
    print("🚀 ЗАПУСК НОВОСТНОГО АГРЕГАТОРА")
    print("=" * 50)
    print(f"✅ Канал: {CHANNEL_ID}")
    print(f"🔥 Каналов для парсинга: {len(SOURCE_CHANNELS)}")
    
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
