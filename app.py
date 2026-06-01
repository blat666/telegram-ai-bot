from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import Application, CommandHandler
import requests
import datetime
import os

# --- Flask для Render ---
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Бот работает!"

@app_flask.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app_flask.run(host='0.0.0.0', port=port)

# --- Telegram бот ---
TOKEN = "8730742431:AAE8qStJGKx1fRkD8AEUd7k98AESixEECCQ"
NEWS_API_KEY = "3add7899f6c845a992102b61cf46c437"

async def get_real_news():
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": "artificial intelligence OR AI",
            "language": "ru",
            "sortBy": "publishedAt",
            "apiKey": NEWS_API_KEY,
            "pageSize": 5
        }
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get("status") == "ok":
            articles = data.get("articles", [])
            if not articles:
                return None
            
            digest_text = f"🤖 *Дайджест ИИ-новостей* от {datetime.datetime.now().strftime('%d.%m.%Y')}\n\n"
            for i, article in enumerate(articles[:5], 1):
                title = article.get("title", "Без названия")
                url_article = article.get("url", "#")
                source = article.get("source", {}).get("name", "")
                digest_text += f"{i}. [{title}]({url_article})\n"
                if source:
                    digest_text += f"   📍 *{source}*\n"
                digest_text += "\n"
            return digest_text
        return None
    except Exception as e:
        print(f"Ошибка NewsAPI: {e}")
        return None

async def start(update: Update, context):
    await update.message.reply_text(
        "Привет! Я бот для дайджестов новостей об ИИ 🤖\n\n"
        "/digest — получить свежие новости\n"
        "/help — помощь"
    )

async def help_command(update: Update, context):
    await update.message.reply_text(
        "🤖 *Команды:*\n\n"
        "/digest — дайджест новостей об ИИ\n"
        "/start — приветствие"
    )

async def digest(update: Update, context):
    msg = await update.message.reply_text("🔍 Собираю свежие новости...")
    text = await get_real_news()
    if not text:
        text = "Не удалось загрузить новости. Попробуйте позже."
    await msg.edit_text(text, parse_mode='Markdown')

def run_bot():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("digest", digest))
    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    # Запускаем Flask в отдельном потоке
    thread = Thread(target=run_flask)
    thread.start()
    # Запускаем бота в основном потоке
    run_bot()