```python
import asyncio
import logging
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from mcstatus import JavaServer
import json
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route
import uvicorn

# Налаштування логування
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Конфігурація
BOT_TOKEN = "8274163476:AAEWiqVBsOnYl2Rp2t-Jrz-2nJMDjDKyij4"
SERVER_ADDRESS = "arm.ichtlay.cc"
SERVER_PORT = 25565
URL = os.environ.get("RENDER_EXTERNAL_URL")  # Render надає URL сервісу
PORT = int(os.environ.get("PORT", 8000))  # Порт із змінної середовища, за замовчуванням 8000

class MinecraftServerMonitor:
    def __init__(self, server_address: str, server_port: int = 25565):
        self.server = JavaServer(server_address, server_port)
        self.previous_players = set()
        self.monitoring_chats = set()
        self.data_file = "bot_data.json"
        self.load_data()
        
    def load_data(self):
        """Завантажує збережені дані"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.monitoring_chats = set(data.get('monitoring_chats', []))
                    self.previous_players = set(data.get('previous_players', []))
            except Exception as e:
                logging.error(f"Помилка завантаження даних: {e}")
    
    def save_data(self):
        """Зберігає дані"""
        try:
            data = {
                'monitoring_chats': list(self.monitoring_chats),
                'previous_players': list(self.previous_players)
            }
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Помилка збереження даних: {e}")
    
    async def get_server_status(self):
        """Отримує статус сервера"""
        try:
            status = await asyncio.to_thread(self.server.status)
            players_list = []
            if status.players.sample:
                players_list = [player.name for player in status.players.sample]
            
            return {
                'online': True,
                'players_online': status.players.online,
                'players_max': status.players.max,
                'players_list': players_list
            }
        except Exception as e:
            logging.error(f"Помилка при отриманні статусу сервера: {e}")
            return {'online': False, 'error': str(e)}
    
    async def check_player_changes(self, bot):
        """Перевіряє зміни в списку гравців"""
        status = await self.get_server_status()
        if not status['online']:
            return
        
        current_players = set(status['players_list'])
        
        # Нові гравці (зайшли)
        joined_players = current_players - self.previous_players
        # Гравці, що вийшли
        left_players = self.previous_players - current_players
        
        # Відправляємо повідомлення про зміни
        for chat_id in self.monitoring_chats:
            try:
                for player in joined_players:
                    message = f"🟢 {player} зайшов на сервер\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    await bot.send_message(chat_id=chat_id, text=message)
                
                for player in left_players:
                    message = f"🔴 {player} покинув сервер\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    await bot.send_message(chat_id=chat_id, text=message)
            except Exception as e:
                logging.error(f"Помилка при відправці повідомлення в чат {chat_id}: {e}")
        
        self.previous_players = current_players
        self.save_data()

# Ініціалізація
monitor = MinecraftServerMonitor(SERVER_ADDRESS, SERVER_PORT)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status - Виводить статус сервера з кнопкою оновлення"""
    chat_id = update.effective_chat.id
    # Автоматично увімкнути моніторинг для цього чату
    monitor.monitoring_chats.add(chat_id)
    monitor.save_data()
    
    message = await get_status_message()
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Оновити", callback_data='update_status')]])
    
    await update.message.reply_text(message, reply_markup=keyboard)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник натискання кнопки"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'update_status':
        message = await get_status_message()
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Оновити", callback_data='update_status')]])
        
        await query.edit_message_text(text=message, reply_markup=keyboard)

async def get_status_message():
    """Генерує повідомлення зі статусом у вказаному форматі"""
    status = await monitor.get_server_status()
    update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    ip = f"{SERVER_ADDRESS}"
    online_status = "🟢 Онлайн" if status['online'] else "🔴 Офлайн"
    players = f"Гравців: {status.get('players_online', 0)}\\{status.get('players_max', 0)}" if status['online'] else "Гравців: N/A"
    
    nicknames = ""
    if status['online'] and status['players_list']:
        nicknames = "\n| — " + "\n| — ".join(status['players_list'])
    elif status['online']:
        nicknames = "\n| — Немає гравців онлайн"
    else:
        nicknames = "\n| — Сервер офлайн"
    
    message = f"Оновлено: {update_time}\n{ip}\n| {online_status}\n| {players}\n| Нікнейми:{nicknames}"
    return message

async def periodic_job(context: ContextTypes.DEFAULT_TYPE):
    """Періодична перевірка змін гравців"""
    await monitor.check_player_changes(context.bot)

async def telegram(request: Request) -> Response:
    """Обробляє вхідні оновлення від Telegram"""
    try:
        await application.update_queue.put(
            Update.de_json(data=await request.json(), bot=application.bot)
        )
        return Response()
    except Exception as e:
        logger.error(f"Помилка обробки вебхука: {e}")
        return Response(status_code=500)

async def health(_: Request) -> PlainTextResponse:
    """Health check для Render"""
    return PlainTextResponse(content="The bot is still running fine :)")

# Налаштування веб-сервера
starlette_app = Starlette(
    routes=[
        Route("/telegram", telegram, methods=["POST"]),
        Route("/healthcheck", health, methods=["GET"]),
    ]
)

async def main():
    """Налаштування та запуск бота"""
    global application
    application = Application.builder().token(BOT_TOKEN).updater(None).build()
    
    # Додаємо обробники
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CallbackQueryHandler(button))
    
    # Налаштування вебхука
    await application.bot.set_webhook(url=f"{URL}/telegram", allowed_updates=Update.ALL_TYPES)
    
    # Періодична задача (кожні 10 секунд)
    job_queue = application.job_queue
    job_queue.run_repeating(periodic_job, interval=10, first=10)
    
    # Запуск бота та веб-сервера
    async with application:
        await application.start()
        await uvicorn.Server(
            config=uvicorn.Config(
                app=starlette_app,
                port=PORT,
                use_colors=False,
                host="0.0.0.0"  # Render вимагає прив’язку до всіх IP
            )
        ).serve()
        await application.stop()

if __name__ == "__main__":
    asyncio.run(main())
```
