import discord
from discord.ext import commands
import os
import re
import aiohttp
import io
from PIL import Image, ImageOps, ImageEnhance
from dotenv import load_dotenv
import threading
from flask import Flask
import pytesseract
import asyncio
import functools
from collections import deque

# --- SERVER GIỮ BOT ONLINE ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot OCR Embed Speed Mode."
def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264

# Cache chống spam (50 tin gần nhất)
processed_cache = deque(maxlen=50)

# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def solve_ocr_fast(image_bytes):
    """
    ENGINE XỬ LÝ SIÊU TỐC (GIỮ NGUYÊN)
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w_img, h_img = img.size
        
        # Thông số cắt ảnh (Đã fix lỗi mất số đầu)
        card_w = w_img / 3
        ratio_top, ratio_bottom = 0.88, 0.94
        ratio_left, ratio_right = 0.54, 0.78 

        crops = []
        for i in range(3):
            # 1. CẮT
            card_x_start = int(i * card_w)
            box = (
                int(card_x_start + (card_w * ratio_left)), 
                int(h_img * ratio_top),                    
                int(card_x_start + (card_w * ratio_right)),
                int(h_img * ratio_bottom)                  
            )
            crop = img.crop(box)

            # 2. XỬ LÝ (Tối ưu tốc độ)
            # Bilinear nhanh hơn Bicubic
            crop = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.BILINEAR)
            crop = crop.convert('L')
            
            # Threshold cứng (Nhanh, nét)
            crop = crop.point(lambda p: 255 if p > 140 else 0)
            
            # Đảo màu + Viền trắng an toàn
            crop = ImageOps.invert(crop)
            crop = ImageOps.expand(crop, border=10, fill='white')
            
            crops.append(crop)

        # 3. GỘP ẢNH
        w_c, h_c = crops[0].size
        gap = 60
        total_w = (w_c * 3) + (gap * 2)
        
        final_img = Image.new('L', (total_w, h_c), color=255)
        final_img.paste(crops[0], (0, 0))
        final_img.paste(crops[1], (w_c + gap, 0))
        final_img.paste(crops[2], ((w_c + gap) * 2, 0))

        # 4. OCR
        # Tắt invert tự động của Tesseract để tăng tốc
        custom_config = r"--psm 7 -c tessedit_char_whitelist=0123456789- -c tessedit_do_invert=0"
        text = pytesseract.image_to_string(final_img, config=custom_config)
        
        # 5. TÁCH SỐ
        matches = re.findall(r'\d+(?:-\d+)?', text)
        results = []
        for i in range(3):
            if i < len(matches):
                results.append(matches[i])
            else:
                results.append("???")
        
        return results

    except Exception:
        return []

# --- BOT DISCORD ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'✨ BOT EMBED READY: {bot.user}')

@bot.event
async def on_message(message):
    if message.author.id != KARUTA_ID: return
    if not message.attachments: return
    
    # Chống spam
    if message.id in processed_cache: return
    processed_cache.append(message.id)

    try:
        att = message.attachments[0]
        if "image" not in att.content_type: return

        # Tải ảnh Async
        async with aiohttp.ClientSession() as session:
            async with session.get(att.url) as resp:
                if resp.status != 200: return
                image_bytes = await resp.read()

        # Xử lý ở luồng phụ
        loop = asyncio.get_running_loop()
        numbers = await loop.run_in_executor(None, functools.partial(solve_ocr_fast, image_bytes))

        if numbers:
            # --- TẠO EMBED ĐẸP ---
            embed = discord.Embed(
                color=0x36393f, # Màu xám tối Discord
                timestamp=message.created_at
            )
            embed.set_footer(text="⚡ Fast OCR") 

            description = ""
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            
            for i, num in enumerate(numbers):
                if num in ["???", "Err", ""]:
                    description += f"▪️ {emojis[i]} | ⚠️ **Unknown**\n"
                else:
                    description += f"▪️ {emojis[i]} | **#{num}**\n"
            
            embed.description = description
            
            # Gửi Embed
            await message.reply(embed=embed, mention_author=False)

    except Exception as e:
        print(f"Lỗi: {e}")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
    else:
        print("❌ Thiếu Token")
