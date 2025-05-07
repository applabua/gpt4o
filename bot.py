#!/usr/bin/env python3
# coding: utf-8

import os
import sys
import logging
import re
import time
from datetime import datetime
from urllib.parse import urlencode

import openai
import urllib3
# Monkey‑patch vendored urllib3 for python-telegram-bot
# Map vendored root and submodules to system urllib3 modules
sys.modules['telegram.vendor.ptb_urllib3.urllib3'] = urllib3
sys.modules['telegram.vendor.ptb_urllib3.urllib3.contrib'] = urllib3.contrib
sys.modules['telegram.vendor.ptb_urllib3.urllib3.contrib.appengine'] = urllib3.contrib.appengine
sys.modules['telegram.vendor.ptb_urllib3.urllib3.packages'] = urllib3.packages
sys.modules['telegram.vendor.ptb_urllib3.urllib3.packages.six'] = urllib3.packages.six
sys.modules['telegram.vendor.ptb_urllib3.urllib3.packages.six.moves'] = urllib3.packages.six.moves
sys.modules['telegram.vendor.ptb_urllib3.urllib3.packages.six.moves.http_client'] = urllib3.packages.six.moves.http_client

import telegram.utils.request
from telegram import Update, BotCommand, MenuButtonCommands
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ——— Force UTF-8 for form data in telegram requests ———
def _encode_body(self, data):
    return urlencode(data).encode("utf-8")

telegram.utils.request.Request._encode_body = _encode_body

# ——— Sanitizer for problematic characters ———
def sanitize(text: str) -> str:
    return text.replace("\u2011", "-")

# ——— Configuration from environment ———
BOT_TOKEN         = os.environ["BOT_TOKEN"]
OPENAI_API_KEY    = os.environ["OPENAI_API_KEY"]
ADMIN_ID          = int(os.environ.get("ADMIN_ID", "2045410830"))
CHANNEL_LINK      = os.environ.get("CHANNEL_LINK", "https://t.me/applab_ua")
WELCOME_IMAGE_URL = os.environ.get("WELCOME_IMAGE_URL", "https://i.ibb.co/FLkjGL5X/IMG-0285.png")

# Initialize OpenAI
openai.api_key = OPENAI_API_KEY

# ——— Logging ———
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Store history of requests for admin
request_history = []

SYSTEM_PROMPT = (
    "You are an AI assistant developed by AppLab, with access to the latest world knowledge, "
    "including real-time news, Wikipedia, and all public internet sources. It is now {date}. "
    "Answer queries accurately, translate between any languages, generate professional images, "
    "and edit photos per user instructions."
)

SELF_PATTERNS = [
    r"опиши себя", r"о тебе", r"скажи о себе", r"кто ты",
    r"describe yourself", r"tell me about yourself"
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.username or user.full_name

    # Notify admin
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔔 Бот відкрився: @{name} (id: {user.id})"
    )

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
        logger.warning(f"Не вдалося надіслати вітальне зображення: {e}")
        await update.message.reply_text(sanitize(greeting), parse_mode=ParseMode.MARKDOWN)

    context.user_data['started'] = True

async def gpt4o(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text.strip()

    # Self-description handling
    for pat in SELF_PATTERNS:
        if re.search(pat, prompt, re.IGNORECASE):
            desc = (
                "Я — універсальний AI-асистент від AppLab, створений компанією AppLab. "
                "Мене створив засновник компанії AppLab Evgeniy Kolokolov. "
                f"Деталі за [ссилкою]({CHANNEL_LINK})."
            )
            return await update.message.reply_text(sanitize(desc), parse_mode=ParseMode.MARKDOWN)

    # Log request for admin
    user = update.effective_user
    uname = user.username or user.full_name
    request_history.append(
        f"<a href='tg://user?id={user.id}'>@{uname}</a> → GPT-4o: {prompt}"
    )

    await update.message.chat.send_action("typing")

    today = datetime.now().strftime("%Y-%m-%d")
    system_msg = {'role':'system', 'content': SYSTEM_PROMPT.format(date=today)}

    chat_hist = context.chat_data.setdefault('history', [])
    chat_hist.append({'role':'user','content':prompt})

    messages = [system_msg] + chat_hist[-20:]

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.5,
            max_tokens=1500
        )
        out = resp.choices[0].message.content.strip()
        out = sanitize(out)
        chat_hist.append({'role':'assistant','content':out})
        await update.message.reply_text(out)
    except Exception as e:
        logger.error(f"GPT-4o error: {e}")
        await update.message.reply_text("⚠️ Помилка OpenAI. Спробуйте пізніше.")

async def image_gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text.strip()
    user = update.effective_user
    uname = user.username or user.full_name
    request_history.append(f"<a href='tg://user?id={user.id}'>@{uname}</a> → Image: {prompt}")

    full_prompt = f"High-resolution professional image, realistic style, 4k: {prompt}"
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
            logger.warning(f"Image attempt failed: {e}")
            time.sleep(1)
    await update.message.reply_text("⚠️ Не вдалося згенерувати картинку після кількох спроб.")

async def edit_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        return await update.message.reply_text("⚠️ Щоб редагувати, відповідайте на фото та напишіть '/edit <опис>'")

    prompt = update.message.text.partition(' ')[2].strip()
    user = update.effective_user
    uname = user.username or user.full_name
    request_history.append(f"<a href='tg://user?id={user.id}'>@{uname}</a> → Edit Image: {prompt}")

    full_prompt = f"Professional photo editing, enhanced: {prompt}"
    photo = update.message.reply_to_message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    path = f"/mnt/data/{photo.file_id}.png"
    await file.download_to_drive(path)

    for _ in range(3):
        await update.message.chat.send_action('upload_photo')
        try:
            resp = openai.Image.create_edit(
                image=open(path,'rb'),
                mask=None,
                prompt=full_prompt,
                n=1,
                size="1024x1024",
                model="dall-e-3"
            )
            url = resp['data'][0]['url']
            return await update.message.reply_photo(photo=url, caption=f"✏️ {prompt}")
        except Exception as e:
            logger.warning(f"Edit attempt failed: {e}")
            time.sleep(1)
    await update.message.reply_text("⚠️ Помилка редагування фото після кількох спроб.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if re.search(r"\b(нарисуй|рисуй|draw|paint|create|generate)\b", text, re.IGNORECASE):
        return await image_gen(update, context)
    if text.lower().startswith('/edit'):
        return await edit_image(update, context)
    return await gpt4o(update, context)

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Невідома команда. Просто напишіть свій запит або '/edit' у відповіді на фото.")

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await app.bot.set_my_commands([BotCommand("start","🚀 Старт")])


def main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("edit", edit_image))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))
    app.run_polling()

if __name__ == '__main__':
    main()
