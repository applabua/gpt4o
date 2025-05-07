# coding=utf-8
import logging
import re
import time
import os
from datetime import datetime
from telegram import Update, BotCommand, MenuButtonCommands
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import openai

# ——— Налаштування через змінні оточення ———
BOT_TOKEN      = os.environ["BOT_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
ADMIN_ID       = int(os.environ.get("ADMIN_ID", "2045410830"))
CHANNEL_LINK   = "https://t.me/applab_ua"
WELCOME_IMAGE_URL = "https://i.ibb.co/FLkjGL5X/IMG-0285.png"

# Ініціалізація OpenAI API ключа
openai.api_key = OPENAI_API_KEY

# ——— Логування ———
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Зберігання запитів для адміна
request_history = []

# Системний промпт для GPT-4o
SYSTEM_PROMPT = (
    "You are an AI assistant developed by AppLab, with access to the latest world knowledge, "
    "including real-time news, Wikipedia, and all public internet sources. It is now {date}. "
    "Answer queries accurately, translate between any languages, generate professional images, "
    "and edit photos per user instructions."
)

# Ключові фрази для опису бота
SELF_PATTERNS = [
    r"опиши себя", r"о тебе", r"скажи о себе", r"кто ты",
    r"describe yourself", r"tell me about yourself"
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Відправляє привітальне фото та текст одним повідомленням"""
    user = update.effective_user
    name = user.username or user.full_name

    # Сповіщення адміну
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔔 Бот відкрився: @{name} (id: {user.id})"
    )

    # Привітальний текст
    greeting = (
        "*👋 Привіт!*\n"
        f"Я — універсальний AI-асистент від [AppLab]({CHANNEL_LINK}) 🤖\n\n"
        "*✍️ Створюю та редагую тексти*\n"
        "*🌍 Перекладаю будь-якою мовою світу*\n"
        "*🎨 Генерую професійні зображення*\n"
        "*💻 Пишу та пояснюю код*\n\n"
        "📩 Просто напишіть свій запит у чаті — і я все зроблю!"
    )

    try:
        await update.message.reply_photo(
            photo=WELCOME_IMAGE_URL,
            caption=greeting,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.warning(f"Не вдалося надіслати фото: {e}")
        await update.message.reply_text(greeting, parse_mode=ParseMode.MARKDOWN)

    context.user_data['started'] = True

async def gpt4o(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє текстові запити через GPT-4o"""
    prompt = update.message.text.strip()

    # Якщо питають про бота
    for pat in SELF_PATTERNS:
        if re.search(pat, prompt, re.IGNORECASE):
            desc = (
                "Я — універсальний AI-асистент від AppLab, створений Evgeniy Kolokolov. "
                f"Деталі: [AppLab]({CHANNEL_LINK})."
            )
            return await update.message.reply_text(desc, parse_mode=ParseMode.MARKDOWN)

    # Лог для адміна
    user = update.effective_user
    uname = user.username or user.full_name
    request_history.append(
        f"<a href='tg://user?id={user.id}'>@{uname}</a> -> GPT: {prompt}"
    )

    # Показуємо, що бот друкує
    await update.message.chat.send_action('typing')

    # Формуємо історію повідомлень
    today = datetime.now().strftime('%Y-%m-%d')
    system_msg = {'role': 'system', 'content': SYSTEM_PROMPT.format(date=today)}
    chat_hist = context.chat_data.setdefault('history', [])
    chat_hist.append({'role': 'user', 'content': prompt})
    messages = [system_msg] + chat_hist[-20:]

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.5,
            max_tokens=1500
        )
        out = resp.choices[0].message.content.strip()
        chat_hist.append({'role': 'assistant', 'content': out})
        await update.message.reply_text(out)
    except Exception as e:
        logger.error(f"GPT-4o error: {e}")
        await update.message.reply_text("⚠️ Помилка OpenAI. Спробуйте пізніше.")

async def image_gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерує зображення через DALL·E 3"""
    prompt = update.message.text.strip()
    user = update.effective_user
    uname = user.username or user.full_name
    request_history.append(f"<a href='tg://user?id={user.id}'>@{uname}</a> -> Img: {prompt}")

    full_prompt = f"High-resolution professional image: {prompt}"
    for _ in range(3):
        await update.message.chat.send_action('upload_photo')
        try:
            resp = openai.Image.create(
                prompt=full_prompt,
                n=1,
                size="1024x1024",
                model="dall-e-3"
            )
            url = resp['data'][0]['url']
            return await update.message.reply_photo(photo=url, caption=f"🎨 {prompt}")
        except Exception as e:
            logger.warning(f"Image failed: {e}")
            time.sleep(1)
    await update.message.reply_text("⚠️ Не вдалося згенерувати картинку.")

async def edit_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Редагує фото через DALL·E 3"""
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        return await update.message.reply_text("⚠️ Щоб редагувати, відповідайте на фото '/edit опис'.")

    prompt = update.message.text.partition(' ')[2].strip()
    user = update.effective_user
    uname = user.username or user.full_name
    request_history.append(f"<a href='tg://user?id={user.id}'>@{uname}</a> -> Edit: {prompt}")

    photo = update.message.reply_to_message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    path = f"/mnt/data/{photo.file_id}.png"
    await file.download_to_drive(path)

    full_prompt = f"Professional photo editing: {prompt}"
    for _ in range(3):
        await update.message.chat.send_action('upload_photo')
        try:
            resp = openai.Image.create_edit(
                image=open(path, 'rb'),
                mask=None,
                prompt=full_prompt,
                n=1,
                size="1024x1024",
                model="dall-e-3"
            )
            url = resp['data'][0]['url']
            return await update.message.reply_photo(photo=url, caption=f"✏️ {prompt}")
        except Exception as e:
            logger.warning(f"Edit failed: {e}")
            time.sleep(1)
    await update.message.reply_text("⚠️ Помилка редагування.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if re.search(r"\b(нарисуй|рисуй|draw|paint|create|generate)\b", text, re.IGNORECASE):
        return await image_gen(update, context)
    if text.lower().startswith('/edit'):
        return await edit_image(update, context)
    return await gpt4o(update, context)

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Невідома команда. Напишіть запит або '/edit'.")

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Відправляє адміну історію запитів"""
    if update.effective_user.id != ADMIN_ID:
        return
    if not request_history:
        return await update.message.reply_text("📭 Історія порожня.")
    await update.message.reply_text(
        "📜 Останні запити:\n" + "\n".join(request_history[-20:]),
        parse_mode=ParseMode.HTML
    )

async def post_init(app):
    await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    await app.bot.set_my_commands([BotCommand("start", "🚀 Старт")])


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("edit", edit_image))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))
    app.run_polling()


if __name__ == '__main__':
    main()
