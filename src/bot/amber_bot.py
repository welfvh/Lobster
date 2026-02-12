#!/usr/bin/env python3
"""
Amber Bot - Telegram bot for Amber AI companion

Separate Telegram bot identity for Amber, sharing the same
file-based message passing system as Lobster.

Messages are tagged with source "telegram-amber" to distinguish
from Lobster's "telegram" source.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Configuration from environment
BOT_TOKEN = os.environ.get("AMBER_BOT_TOKEN", "")
ALLOWED_USERS = [int(x) for x in os.environ.get("AMBER_ALLOWED_USERS", os.environ.get("TELEGRAM_ALLOWED_USERS", "")).split(",") if x.strip()]
SOURCE_ID = "telegram-amber"

if not BOT_TOKEN:
    raise ValueError("AMBER_BOT_TOKEN environment variable is required")
if not ALLOWED_USERS:
    raise ValueError("AMBER_ALLOWED_USERS (or TELEGRAM_ALLOWED_USERS) environment variable is required")

INBOX_DIR = Path.home() / "messages" / "inbox"
OUTBOX_DIR = Path.home() / "messages" / "outbox"
AUDIO_DIR = Path.home() / "messages" / "audio"
IMAGES_DIR = Path.home() / "messages" / "images"

# Ensure directories exist
INBOX_DIR.mkdir(parents=True, exist_ok=True)
OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# Logging
LOG_DIR = Path.home() / "lobster-workspace" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "amber-bot.log"),
    ],
)
log = logging.getLogger("amber")

# Global reference to the bot app and event loop for sending replies
bot_app = None
main_loop = None


class OutboxHandler(FileSystemEventHandler):
    """Watches outbox for reply files and sends them via Telegram (Amber bot only)."""

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith('.json'):
            if bot_app and main_loop and main_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.process_reply(event.src_path),
                    main_loop
                )

    async def process_reply(self, filepath):
        try:
            await asyncio.sleep(0.1)  # Brief delay to ensure file is written
            with open(filepath, 'r') as f:
                reply = json.load(f)

            # Only process replies intended for Amber
            if reply.get('source', '').lower() != SOURCE_ID:
                return

            chat_id = reply.get('chat_id')
            text = reply.get('text', '')
            buttons = reply.get('buttons')

            if chat_id and text and bot_app:
                reply_markup = build_inline_keyboard(buttons) if buttons else None
                try:
                    await bot_app.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="Markdown",
                        reply_markup=reply_markup
                    )
                except Exception:
                    # Fallback to plain text if Markdown parsing fails
                    await bot_app.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=reply_markup
                    )
                log.info(f"Sent reply to {chat_id}: {text[:50]}...")

            # Remove processed file
            os.remove(filepath)

        except Exception as e:
            log.error(f"Error processing reply {filepath}: {e}")


async def process_existing_outbox():
    """Process any outbox files that exist on startup."""
    handler = OutboxHandler()
    existing_files = list(OUTBOX_DIR.glob("*.json"))
    if existing_files:
        log.info(f"Processing {len(existing_files)} existing outbox file(s)...")
        for filepath in existing_files:
            await handler.process_reply(str(filepath))


def is_authorized(user_id: int) -> bool:
    return user_id in ALLOWED_USERS


def build_inline_keyboard(buttons: list) -> InlineKeyboardMarkup | None:
    """Build an InlineKeyboardMarkup from a buttons specification."""
    if not buttons or not isinstance(buttons, list):
        return None

    keyboard = []
    for row in buttons:
        if not isinstance(row, list):
            continue
        keyboard_row = []
        for button in row:
            if isinstance(button, str):
                keyboard_row.append(InlineKeyboardButton(text=button, callback_data=button))
            elif isinstance(button, dict):
                text = button.get('text', '')
                callback_data = button.get('callback_data', text)
                if text:
                    keyboard_row.append(InlineKeyboardButton(text=text, callback_data=callback_data))
        if keyboard_row:
            keyboard.append(keyboard_row)

    return InlineKeyboardMarkup(keyboard) if keyboard else None


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button presses."""
    query = update.callback_query
    user = query.from_user

    if not is_authorized(user.id):
        await query.answer("Unauthorized", show_alert=True)
        return

    await query.answer()

    msg_id = f"{int(time.time() * 1000)}_{query.id}"
    callback_data = query.data

    msg_data = {
        "id": msg_id,
        "source": SOURCE_ID,
        "type": "callback",
        "chat_id": query.message.chat_id,
        "user_id": user.id,
        "username": user.username,
        "user_name": user.first_name,
        "text": f"[Button pressed: {callback_data}]",
        "callback_data": callback_data,
        "callback_query_id": query.id,
        "original_message_id": query.message.message_id,
        "original_message_text": query.message.text,
        "timestamp": datetime.utcnow().isoformat(),
    }

    inbox_file = INBOX_DIR / f"{msg_id}.json"
    with open(inbox_file, 'w') as f:
        json.dump(msg_data, f, indent=2)

    log.info(f"Button press from {user.first_name}: {callback_data}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text("Unauthorized.")
        return

    await update.message.reply_text(
        f"Hey {user.first_name} — I'm Amber, your AI companion.\n\n"
        "Messages you send here come directly to me."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message

    if not is_authorized(user.id):
        log.warning(f"Unauthorized: {user.id}")
        return

    msg_id = f"{int(time.time() * 1000)}_{message.message_id}"

    # Handle voice messages
    if message.voice:
        await handle_voice_message(update, context, msg_id)
        return

    # Handle photo messages
    if message.photo:
        await handle_photo_message(update, context, msg_id)
        return

    # Handle document/file messages
    if message.document:
        await handle_document_message(update, context, msg_id)
        return

    text = message.text
    if not text:
        return

    msg_data = {
        "id": msg_id,
        "source": SOURCE_ID,
        "chat_id": message.chat_id,
        "user_id": user.id,
        "username": user.username,
        "user_name": user.first_name,
        "text": text,
        "timestamp": datetime.utcnow().isoformat(),
    }

    inbox_file = INBOX_DIR / f"{msg_id}.json"
    with open(inbox_file, 'w') as f:
        json.dump(msg_data, f, indent=2)

    log.info(f"Wrote message to inbox: {msg_id}")


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE, msg_id: str):
    """Handle voice messages."""
    user = update.effective_user
    message = update.message
    voice = message.voice

    try:
        file = await context.bot.get_file(voice.file_id)
        audio_filename = f"{msg_id}.ogg"
        audio_path = AUDIO_DIR / audio_filename

        await file.download_to_drive(audio_path)
        log.info(f"Downloaded voice message to: {audio_path}")

        msg_data = {
            "id": msg_id,
            "source": SOURCE_ID,
            "type": "voice",
            "chat_id": message.chat_id,
            "user_id": user.id,
            "username": user.username,
            "user_name": user.first_name,
            "text": "[Voice message - pending transcription]",
            "audio_file": str(audio_path),
            "audio_duration": voice.duration,
            "audio_mime_type": voice.mime_type or "audio/ogg",
            "file_id": voice.file_id,
            "timestamp": datetime.utcnow().isoformat(),
        }

        inbox_file = INBOX_DIR / f"{msg_id}.json"
        with open(inbox_file, 'w') as f:
            json.dump(msg_data, f, indent=2)

        log.info(f"Wrote voice message to inbox: {msg_id}")

    except Exception as e:
        log.error(f"Error handling voice message: {e}")
        await message.reply_text("Failed to process voice message.")


async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE, msg_id: str):
    """Handle photo messages."""
    user = update.effective_user
    message = update.message

    try:
        photo = message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_filename = f"{msg_id}.jpg"
        image_path = IMAGES_DIR / image_filename

        await file.download_to_drive(image_path)
        log.info(f"Downloaded photo to: {image_path}")

        caption = message.caption or ""

        msg_data = {
            "id": msg_id,
            "source": SOURCE_ID,
            "type": "photo",
            "chat_id": message.chat_id,
            "user_id": user.id,
            "username": user.username,
            "user_name": user.first_name,
            "text": caption if caption else "[Photo - see image_file]",
            "image_file": str(image_path),
            "image_width": photo.width,
            "image_height": photo.height,
            "file_id": photo.file_id,
            "timestamp": datetime.utcnow().isoformat(),
        }

        inbox_file = INBOX_DIR / f"{msg_id}.json"
        with open(inbox_file, 'w') as f:
            json.dump(msg_data, f, indent=2)

        log.info(f"Wrote photo message to inbox: {msg_id}")

    except Exception as e:
        log.error(f"Error handling photo message: {e}")
        await message.reply_text("Failed to process image.")


async def handle_document_message(update: Update, context: ContextTypes.DEFAULT_TYPE, msg_id: str):
    """Handle document messages."""
    user = update.effective_user
    message = update.message
    document = message.document

    try:
        mime_type = document.mime_type or ""
        is_image = mime_type.startswith("image/")
        original_name = document.file_name or "file"
        file_size_mb = (document.file_size or 0) / (1024 * 1024)

        if file_size_mb > 20:
            await message.reply_text(f"File too large ({file_size_mb:.1f}MB). Limit is 20MB.")
            return

        file = await context.bot.get_file(document.file_id)
        ext = Path(original_name).suffix or (".jpg" if is_image else "")

        if is_image:
            save_path = IMAGES_DIR / f"{msg_id}{ext}"
        else:
            files_dir = Path.home() / "messages" / "files"
            files_dir.mkdir(parents=True, exist_ok=True)
            save_path = files_dir / f"{msg_id}{ext}"

        await file.download_to_drive(save_path)
        log.info(f"Downloaded document to: {save_path}")

        caption = message.caption or ""

        msg_data = {
            "id": msg_id,
            "source": SOURCE_ID,
            "type": "image" if is_image else "document",
            "chat_id": message.chat_id,
            "user_id": user.id,
            "username": user.username,
            "user_name": user.first_name,
            "text": caption if caption else f"[Document: {original_name}]",
            "file_path": str(save_path),
            "file_name": original_name,
            "mime_type": mime_type,
            "file_size": document.file_size,
            "file_id": document.file_id,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if is_image:
            msg_data["image_file"] = str(save_path)

        inbox_file = INBOX_DIR / f"{msg_id}.json"
        with open(inbox_file, 'w') as f:
            json.dump(msg_data, f, indent=2)

        log.info(f"Wrote document message to inbox: {msg_id}")

    except Exception as e:
        log.error(f"Error handling document: {e}", exc_info=True)
        await message.reply_text(f"Failed to process file.")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log.error(f"Error: {context.error}", exc_info=context.error)


async def run_bot():
    global bot_app, main_loop

    log.info("Starting Amber Bot...")
    log.info(f"Source ID: {SOURCE_ID}")
    log.info(f"Inbox: {INBOX_DIR}")
    log.info(f"Outbox: {OUTBOX_DIR}")

    main_loop = asyncio.get_running_loop()

    # Set up outbox watcher
    observer = Observer()
    observer.schedule(OutboxHandler(), str(OUTBOX_DIR), recursive=False)
    observer.start()
    log.info("Watching outbox for replies...")

    # Create bot application
    bot_app = Application.builder().token(BOT_TOKEN).build()

    # Add handlers
    bot_app.add_handler(CommandHandler("start", start_command))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    bot_app.add_handler(MessageHandler(filters.VOICE, handle_message))
    bot_app.add_handler(MessageHandler(filters.PHOTO, handle_message))
    bot_app.add_handler(MessageHandler(filters.Document.ALL, handle_message))
    bot_app.add_handler(CallbackQueryHandler(handle_callback_query))
    bot_app.add_error_handler(error_handler)

    # Initialize and start
    await bot_app.initialize()
    await bot_app.start()
    log.info("Amber bot is now polling...")

    # Process any existing outbox files from before startup
    await process_existing_outbox()

    try:
        await bot_app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        while True:
            await asyncio.sleep(1)
    finally:
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()
        observer.stop()
        observer.join()


def main():
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
