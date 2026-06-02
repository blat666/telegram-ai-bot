import asyncio
import datetime
import hashlib
import os
from threading import Thread
from flask import Flask
import requests
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

# ---------- Получение новостей через NewsAPI ----------
def fetch_news():
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": "искусственный интеллект OR нейросети OR AI",
            "language": "ru",
            "sortBy": "publishedAt",
            "apiKey": NEWS_API_KEY,
            "pageSize": 5
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
                "description": article.get("description", "")[:200]
            })
        
        print(f"📰 Собрано новостей: {len(news_list)}")
        return news_list
    except Exception as e:
        print(f"❌ Ошибка NewsAPI: {e}")
        return []

def format_news(news):
    message = f"🤖 *{news['source']}*\n"
    message += f"📰 [{news['title']}]({news['link']})\n"
    if news['description']:
        message += f"\n📝 {news['description']}\n"
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
    await update.message.reply_text("🤖 Новостной агрегатор ИИ (NewsAPI)\n/status — статистика")

async def status_command(update: Update, context):
    await update.message.reply_text(f"📊 Новостей в памяти: {len(published_ids)}\n⏱ Интервал: {CHECK_INTERVAL // 60} мин\n📡 Источник: NewsAPI")

# ---------- Запуск ----------
async def main():
    print("=" * 50)
    print("🚀 ЗАПУСК НОВОСТНОГО АГРЕГАТОРА (NewsAPI)")
    print("=" * 50)
    print(f"✅ Канал: {CHANNEL_ID}")
    
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status_command))
    
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
