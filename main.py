import telebot
import yt_dlp
import os
import requests
from bs4 import BeautifulSoup
import time
import shutil

# ==========================================
# কনফিগারেশন সেকশন
# ==========================================
BOT_TOKEN = 'YOUR_BOT_TOKEN_HERE'  # আপনার বটের টোকেন এখানে দিন
DOWNLOAD_FOLDER = "downloads"

# বট ইনিশিলাইজেশন
bot = telebot.TeleBot(BOT_TOKEN)

# ফোল্ডার না থাকলে তৈরি করে নেবে
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# ==========================================
# হেল্পার ফাংশন: পেজ থেকে ভিডিও লিংক খোঁজা (Smart Detection)
# ==========================================
def find_embedded_video(url):
    """
    এই ফাংশনটি GilliTV বা ব্লগের মতো সাইটে লুকানো ভিডিও লিংক খুঁজে বের করে।
    """
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # ১. সরাসরি iframe খোঁজা
            iframes = soup.find_all('iframe')
            for iframe in iframes:
                src = iframe.get('src')
                # পরিচিত ভিডিও প্লেয়ার ফিল্টার করা
                if src and any(x in src for x in ['dailymotion', 'youtube', 'vidoza', 'streamtape', 'ok.ru']):
                    if src.startswith('//'): 
                        return 'https:' + src
                    return src
    except Exception as e:
        print(f"Error scraping: {e}")
    
    return url  # কিছু না পেলে মেইন লিংকটাই ফেরত দেবে

# ==========================================
# প্রোগ্রেস হুক (Progress Bar)
# ==========================================
def progress_hook(d):
    if d['status'] == 'downloading':
        print(f"Downloading: {d['_percent_str']} complete")

# ==========================================
# ভিডিও ডাউনলোড এবং প্রসেসিং ফাংশন
# ==========================================
def download_video(url, message):
    msg = bot.reply_to(message, "🕵️‍♂️ সাইট অ্যানালাইসিস করা হচ্ছে... অনুগ্রহ করে অপেক্ষা করুন।")
    
    # ১. স্মার্ট স্ক্যান: যদি এমবেডেড ভিডিও থাকে তা খুঁজে বের করা
    target_url = find_embedded_video(url)
    
    bot.edit_message_text(f"✅ ভিডিও সোর্স পাওয়া গেছে!\n⬇️ ডাউনলোড শুরু হচ্ছে...\nTarget: {target_url}", chat_id=message.chat.id, message_id=msg.message_id)

    # yt-dlp অপশনস
    ydl_opts = {
        'format': 'best[ext=mp4]/best', # সেরা কোয়ালিটি এবং MP4 ফরম্যাট
        'outtmpl': f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s',
        'noplaylist': True,
        'progress_hooks': [progress_hook],
        'quiet': True,
        'writethumbnail': True, # থাম্বনেইল ডাউনলোড
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # ভিডিওর ইনফরমেশন বের করা
            info = ydl.extract_info(target_url, download=True)
            
            video_title = info.get('title', 'Unknown Video')
            video_path = ydl.prepare_filename(info)
            duration = info.get('duration', 0)
            width = info.get('width', 0)
            height = info.get('height', 0)
            
            # ফাইল সাইজ চেক (Telegram Limit Check)
            file_size = os.path.getsize(video_path)
            file_size_mb = file_size / (1024 * 1024)
            
            # নোট: লোকাল সার্ভার ছাড়া ৫০MB এর বেশি আপলোড হবে না
            if file_size_mb > 49: 
                bot.edit_message_text(f"⚠️ ভিডিওটি ডাউনলোড হয়েছে কিন্তু সাইজ ({file_size_mb:.2f} MB) টেলিগ্রাম বটের সাধারণ লিমিট (50MB) এর চেয়ে বেশি।\n\nবড় ফাইল পাঠাতে হলে 'Local Bot API Server' কনফিগার করতে হবে।", chat_id=message.chat.id, message_id=msg.message_id)
                # ফাইলটি ডিলিট করে দিচ্ছি সার্ভার ক্লিন রাখার জন্য
                if os.path.exists(video_path):
                    os.remove(video_path)
                return

            # টেলিগ্রামে আপলোড
            bot.edit_message_text("⬆️ টেলিগ্রামে আপলোড করা হচ্ছে...", chat_id=message.chat.id, message_id=msg.message_id)
            
            with open(video_path, 'rb') as video_file:
                bot.send_video(
                    message.chat.id, 
                    video_file, 
                    caption=f"🎬 **{video_title}**\n\n✅ Downloaded by Bot", 
                    parse_mode="Markdown",
                    duration=duration,
                    width=width,
                    height=height,
                    supports_streaming=True
                )
            
            # সফল মেসেজ এবং ক্লিনআপ
            bot.delete_message(message.chat.id, msg.message_id)
            bot.reply_to(message, "✅ ভিডিও সফলভাবে পাঠানো হয়েছে!")
            
            # ফাইল মুছে ফেলা (স্টোরেজ সেভ করার জন্য)
            if os.path.exists(video_path):
                os.remove(video_path)
                # থাম্বনেইল থাকলে সেটাও ডিলিট করা
                thumb_path = video_path.rsplit('.', 1)[0] + ".jpg"
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)
                elif os.path.exists(video_path.rsplit('.', 1)[0] + ".webp"):
                     os.remove(video_path.rsplit('.', 1)[0] + ".webp")

    except Exception as e:
        bot.edit_message_text(f"❌ এরর হয়েছে: {str(e)}", chat_id=message.chat.id, message_id=msg.message_id)
        print(e)

# ==========================================
# মেসেজ হ্যান্ডলার
# ==========================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "👋 হ্যালো! আমি একটি অ্যাডভান্সড ভিডিও ডাউনলোডার।\n\nযেকোনো নাটক বা সিরিজের লিংক দিন (যেমন: GilliTV), আমি ভিডিও খুঁজে বের করে ডাউনলোড করে দেব।")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    url = message.text.strip()
    
    if url.startswith("http"):
        download_video(url, message)
    else:
        bot.reply_to(message, "দয়া করে একটি সঠিক লিংক দিন (http বা https দিয়ে শুরু)।")

# বট চালু রাখা
print("🤖 Bot is running...")
bot.infinity_polling()
