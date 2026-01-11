# main.py - DEBUG VERSION

import discord
from discord.ext import commands
import os
import re
import requests
import io
from PIL import Image, ImageOps, ImageStat # Thêm ImageStat để tính độ sáng
from dotenv import load_dotenv
import threading
from flask import Flask
import asyncio
import pytesseract

# --- SERVER ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot OCR Debug Mode On"
def run_web_server():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

# --- CONFIG ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264

def clean_print_number(text):
    if not text: return "???"
    # Lọc rác, chỉ lấy số
    text = re.sub(r'[^\d]', '', text) 
    return text if text else "???"

async def get_print_numbers_from_image(image_bytes):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size
        
        if width < 830 or height < 300: return [], []

        # TỌA ĐỘ CẮT (Đã nới rộng ra một chút để an toàn)
        # Left: 140 | Top: 220 | Right: 275 | Bottom: 248
        # Card gốc: 278x248
        print_box_relative = (140, 222, 275, 248)

        # Cấu hình mỗi thẻ
        x_coords = [0, 279, 558]
        y_offset = 32
        card_width = 278
        card_height = 248

        results = []
        debug_images = [] # Danh sách chứa ảnh đã xử lý để gửi lại Discord

        for i in range(3):
            # 1. Cắt thẻ lớn
            card = img.crop((x_coords[i], y_offset, x_coords[i] + card_width, y_offset + card_height))
            
            # 2. Cắt vùng số
            crop = card.crop(print_box_relative)

            # 3. Xử lý ảnh thông minh
            # Phóng to gấp 4 lần
            crop = crop.resize((crop.width * 4, crop.height * 4), Image.Resampling.LANCZOS)
            
            # Chuyển xám
            crop = crop.convert('L')

            # --- TỰ ĐỘNG NHẬN DIỆN NỀN SÁNG HAY TỐI ---
            stat = ImageStat.Stat(crop)
            avg_brightness = stat.mean[0] # Tính độ sáng trung bình (0-255)
            
            # Nếu ảnh tối (nền đen chữ trắng) -> Đảo màu thành nền trắng chữ đen
            # Nếu ảnh sáng (nền vàng/trắng chữ đen) -> Giữ nguyên
            if avg_brightness < 128:
                crop = ImageOps.invert(crop)

            # Tăng độ tương phản (làm rõ chữ đen trên nền trắng)
            crop = ImageOps.autocontrast(crop, cutoff=5)

            # Lưu ảnh debug vào bộ nhớ để gửi lại Discord
            img_byte_arr = io.BytesIO()
            crop.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            debug_images.append(discord.File(img_byte_arr, filename=f"debug_card_{i+1}.png"))

            # 4. OCR
            # --psm 8: Treat the image as a single word (Tốt cho số đơn lẻ)
            custom_config = r"--psm 8 --oem 3 -c tessedit_char_whitelist=0123456789"
            raw_text = pytesseract.image_to_string(crop, config=custom_config).strip()
            
            cleaned = clean_print_number(raw_text)
            results.append(cleaned)

        return results, debug_images

    except Exception as e:
        print(f"Lỗi: {e}")
        return [], []

# --- BOT ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready(): print(f'✅ Bot Online: {bot.user}')

@bot.event
async def on_message(message):
    if not (message.author.id == KARUTA_ID and message.attachments): return

    print("Phát hiện ảnh Karuta...")
    try:
        response = requests.get(message.attachments[0].url)
        image_bytes = response.content
        
        # Nhận cả kết quả lẫn ảnh debug
        numbers, debug_imgs = await get_print_numbers_from_image(image_bytes)

        if numbers:
            reply_text = ""
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            for i, num in enumerate(numbers):
                reply_text += f"▪️ {emojis[i]} | **#{num}**\n"
            
            # Gửi kết quả kèm theo 3 tấm ảnh bot đã nhìn thấy
            await message.reply(content=reply_text, files=debug_imgs)
            print("Đã gửi kết quả và ảnh debug.")

    except Exception as e:
        print(f"Lỗi: {e}")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
