import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import sqlite3
import re
import os
import threading
from flask import Flask

# گرفتن توکن از سرور
TOKEN = os.environ.get('BOT_TOKEN')
bot = telebot.TeleBot(TOKEN)

# دیتابیس برای ذخیره کیفیت دلخواه شما
conn = sqlite3.connect('settings.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, quality TEXT)''')
conn.commit()

# وب‌سرور ساده برای روشن ماندن ربات در هاست‌های رایگان
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot is Running!"
def run_web():
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 8080)))
threading.Thread(target=run_web).start()

def get_quality(user_id):
    c.execute('SELECT quality FROM users WHERE user_id = ?', (user_id,))
    res = c.fetchone()
    return res[0] if res else '480p'

def set_quality(user_id, quality):
    c.execute('REPLACE INTO users (user_id, quality) VALUES (?, ?)', (user_id, quality))
    conn.commit()

video_tasks = {}

@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.send_message(message.chat.id, "سلام! روی ویدیوی YouGlish کلیک راست کن، گزینه Copy video URL را بزن و لینک را اینجا بفرست.")

@bot.message_handler(commands=['settings'])
def settings_cmd(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("کیفیت 480p (سریع‌تر)", callback_data="q_480p"),
               InlineKeyboardButton("کیفیت 720p", callback_data="q_720p"))
    bot.send_message(message.chat.id, f"کیفیت فعلی شما: {get_quality(message.from_user.id)}\n\nکیفیت جدید را انتخاب کنید:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('q_'))
def set_q_callback(call):
    q = call.data.split('_')[1]
    set_quality(call.from_user.id, q)
    bot.edit_message_text(f"✅ کیفیت پیش‌فرض روی {q} تنظیم شد.", call.message.chat.id, call.message.message_id)

@bot.message_handler(regexp=r"(youtu\.be|youtube\.com)")
def handle_url(message):
    url = message.text
    match = re.search(r"[?&](t|start)=(\d+)", url)
    base_time = int(match.group(2)) if match else 0
    
    video_tasks[message.from_user.id] = {
        'url': url,
        'base_time': base_time,
        'start': max(0, base_time - 5), # شروع از ۵ ثانیه قبل از اصطلاح
        'end': base_time + 10           # پایان ۱۰ ثانیه بعد از اصطلاح
    }
    send_edit_menu(message.chat.id, message.from_user.id)

def send_edit_menu(chat_id, user_id):
    task = video_tasks.get(user_id)
    text = f"⏱ زمان پایه اصطلاح: {task['base_time']} ثانیه\n\n🟢 شروع کلیپ: {task['start']} ثانیه\n🔴 پایان کلیپ: {task['end']} ثانیه"
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
    markup.add(
        InlineKeyboardButton("✍️ ورود دستی شروع", callback_data="manual_start"),
        InlineKeyboardButton("✍️ ورود دستی پایان", callback_data="manual_end")
    )
    markup.add(InlineKeyboardButton("✂️ دانلود ویدیو + زیرنویس", callback_data="download"))
    return markup

@bot.callback_query_handler(func=lambda call: not call.data.startswith('q_'))
def process_video_callback(call):
    user_id = call.from_user.id
    task = video_tasks.get(user_id)
    if not task:
        bot.answer_callback_query(call.id, "لینک ویدیو منقضی شده، لطفاً لینک را دوباره بفرستید.")
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
    
    elif action == 'manual_start':
        msg = bot.send_message(call.message.chat.id, "زمان شروع را به ثانیه وارد کنید:")
        bot.register_next_step_handler(msg, process_manual, user_id, 'start')
        
    elif action == 'manual_end':
        msg = bot.send_message(call.message.chat.id, "زمان پایان را به ثانیه وارد کنید:")
        bot.register_next_step_handler(msg, process_manual, user_id, 'end')

    elif action == 'download':
        bot.edit_message_text("⏳ در حال استخراج، برش ویدیو و چسباندن زیرنویس... لطفاً صبر کنید.", call.message.chat.id, call.message.message_id)
        threading.Thread(target=process_download, args=(call.message.chat.id, user_id)).start()

def update_menu(call):
    task = video_tasks.get(call.from_user.id)
    bot.edit_message_text(f"⏱ زمان پایه: {task['base_time']}\n\n🟢 شروع: {task['start']} | 🔴 پایان: {task['end']}", call.message.chat.id, call.message.message_id, reply_markup=get_markup())

def process_manual(message, user_id, time_type):
    if message.text.isdigit():
        video_tasks[user_id][time_type] = int(message.text)
        send_edit_menu(message.chat.id, user_id)
    else:
        bot.send_message(message.chat.id, "❌ عدد نامعتبر. دوباره امتحان کنید.")

def process_download(chat_id, user_id):
    task = video_tasks.get(user_id)
    q = get_quality(user_id)
    height = 480 if q == '480p' else 720

    ydl_opts = {
        'format': f'bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
        'download_ranges': yt_dlp.utils.download_range_func(None, [(task['start'], task['end'])]),
        'force_keyframes_at_cuts': True,
        'outtmpl': f'video_{user_id}.%(ext)s',
        'quiet': True,
        # کدهای مربوط به دانلود و جاسازی زیرنویس انگلیسی
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['en', 'en-US'],
        'postprocessors': [
            {'key': 'FFmpegSubtitlesConvertor', 'format': 'srt'},
            {'key': 'FFmpegEmbedSubtitle'}
        ],
        'merge_output_format': 'mp4'
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(task['url'], download=True)
            filename = ydl.prepare_filename(info)

        with open(filename, 'rb') as video:
            bot.send_video(chat_id, video, caption=f"✅ کیفیت: {q} | زیرنویس انگلیسی جاسازی شد.")
        os.remove(filename)
    except Exception as e:
        bot.send_message(chat_id, "❌ مشکلی پیش آمد. ویدیو یا زیرنویس در این محدوده زمانی در دسترس نیست.")

bot.polling(none_stop=True)
