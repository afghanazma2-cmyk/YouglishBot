import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import sqlite3
import re
import os
import threading
from flask import Flask

TOKEN = os.environ.get('BOT_TOKEN')
bot = telebot.TeleBot(TOKEN)

conn = sqlite3.connect('settings.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, quality TEXT)''')
conn.commit()

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Running!"

def run_web():
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 8080)))

# این خط بیرون از تابع قرار دارد تا سرور بدون مشکل در پس‌زمینه روشن بماند
threading.Thread(target=run_web).start()

video_tasks = {}

@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.send_message(message.chat.id, "سلام! لینک YouGlish یا یوتیوب را بفرست.")

@bot.message_handler(regexp=r"(youtu\.be|youtube\.com)")
def handle_url(message):
    raw_url = message.text
    clean_url = raw_url.split('&')[0].split('?si=')[0]
    
    match = re.search(r"[?&](t|start)=(\d+)", raw_url)
    if match:
        base_time = int(match.group(2))
    else:
        base_time = 15  
    
    video_tasks[message.from_user.id] = {
        'url': clean_url,
        'base_time': base_time,
        'start': max(0, base_time - 5),
        'end': base_time + 10
    }
    send_edit_menu(message.chat.id, message.from_user.id)

def send_edit_menu(chat_id, user_id):
    task = video_tasks.get(user_id)
    text = f"⏱ زمان پایه: {task['base_time']} ثانیه\n\n🟢 شروع: {task['start']} | 🔴 پایان: {task['end']}"
    bot.send_message(chat_id, text, reply_markup=get_markup())

def get_markup():
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton("-5 ثانیه", callback_data="s_-5"),
        InlineKeyboardButton("-10 ثانیه", callback_data="s_-10"),
        InlineKeyboardButton("دقیقاً همون", callback_data="s_0")
    )
    markup.add(
        InlineKeyboardButton("+5 ثانیه", callback_data="e_5"),
        InlineKeyboardButton("+10 ثانیه", callback_data="e_10")
    )
    markup.add(InlineKeyboardButton("✂️ دانلود سریع ویدیو", callback_data="download"))
    return markup

@bot.callback_query_handler(func=lambda call: True)
def process_video_callback(call):
    user_id = call.from_user.id
    task = video_tasks.get(user_id)
    if not task:
        bot.answer_callback_query(call.id, "لینک منقضی شده، دوباره بفرستید.")
        return

    action = call.data
    if action.startswith('s_'):
        val = int(action.split('_')[1])
        task['start'] = max(0, task['base_time'] + val)
        update_menu(call)
    elif action.startswith('e_'):
        val = int(action.split('_')[1])
        task['end'] = task['base_time'] + val
        update_menu(call)
    elif action == 'download':
        bot.edit_message_text("⏳ در حال استخراج و برش... (ممکن است ۱ دقیقه طول بکشد)", call.message.chat.id, call.message.message_id)
        threading.Thread(target=process_download, args=(call.message.chat.id, user_id)).start()

def update_menu(call):
    task = video_tasks.get(call.from_user.id)
    try:
        bot.edit_message_text(f"⏱ زمان پایه: {task['base_time']} ثانیه\n\n🟢 شروع: {task['start']} | 🔴 پایان: {task['end']}", call.message.chat.id, call.message.message_id, reply_markup=get_markup())
    except Exception:
        pass

def process_download(chat_id, user_id):
    task = video_tasks.get(user_id)

    ydl_opts = {
        'format': 'best[height<=480]/best',
        'download_ranges': yt_dlp.utils.download_range_func(None, [(task['start'], task['end'])]),
        'force_keyframes_at_cuts': True,
        'outtmpl': f'video_{user_id}.%(ext)s',
        'extractor_args': {'youtube': {'player_client': ['android']}},
        'quiet': True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(task['url'], download=True)
            filename = ydl.prepare_filename(info)

        with open(filename, 'rb') as video:
            bot.send_video(chat_id, video, caption="✅ ویدیو با موفقیت برش داده شد.")
        os.remove(filename)
    except Exception as e:
        bot.send_message(chat_id, f"❌ خطای سیستم:\n{str(e)}")

bot.polling(none_stop=True)
