import os
import asyncio
import yt_dlp
from pyrogram import Client, filters

# আপনার তথ্যগুলো এখানে দিন
API_ID = 'YOUR_API_ID'
API_HASH = 'YOUR_API_HASH'
BOT_TOKEN = 'YOUR_BOT_TOKEN'

app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("লিঙ্ক দিন, আমি ২জিবি পর্যন্ত ভিডিও ডাউনলোড করে দিচ্ছি!")

@app.on_message(filters.text & ~filters.command("start"))
async def downloader(client, message):
    url = message.text
    status_msg = await message.reply_text("লিঙ্ক প্রসেস করছি...")

    # ভিডিও ডাউনলোডের সেটিংস
    ydl_opts = {
        'format': 'best',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'noplaylist': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            await status_msg.edit_text("ডাউনলোড শুরু হয়েছে...")
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            title = info.get('title', 'video')

            await status_msg.edit_text("ডাউনলোড শেষ! এখন ২জিবি লিমিটে আপলোড করছি...")

            # ভিডিও আপলোড (Pyrogram বড় ফাইল সাপোর্ট করে)
            await client.send_video(
                chat_id=message.chat.id,
                video=file_path,
                caption=title,
                supports_streaming=True
            )

            os.remove(file_path) # ফাইল ডিলিট করা
            await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"ভুল হয়েছে: {str(e)}")

if __name__ == "__main__":
    if not os.path.exists('downloads'):
        os.makedirs('downloads')
    app.run()
