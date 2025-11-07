import threading
from webserver import run as run_webserver
from your_bot_code import bot

threading.Thread(target=run_webserver, daemon=True).start()
bot.infinity_polling(timeout=60,long_polling_timeout=30)
