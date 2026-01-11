# main.py - Phiên bản FIX LỖI TRẮNG ẢNH (Smart Contrast)

import discord
from discord.ext import commands
import os
import re
import requests
import io
from PIL import Image, ImageOps, ImageEnhance
from dotenv import load_dotenv
import threading
from flask import Flask
import asyncio
import pytesseract

# --- SERVER ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot OCR Karuta Fix White Image"
def run_web_server():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264

# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def extract_print_number(text):
    """Lọc lấy số in từ kết quả OCR"""
    if not text: return "???"
    # Thay thế các ký tự nhầm lẫn phổ biến
    text = text.replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1")
    text = text.replace("S", "5").replace("s", "5")
    
    # Tìm chuỗi số đứng trước dấu gạch ngang (ví dụ: 1234-1)
    match = re.search(r'(\d+)[-.]', text)
    if match:
        return match.group(1)
    
    # Nếu không, lấy chuỗi số dài nhất tìm được
    numbers = re.findall(r'\d+', text)
    if numbers:
        return max(numbers, key=len)
    return "???"

async def get_print_numbers_from_image(image_bytes):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w_img, h_img = img.size
        
        card_w = w_img / 3
        
        # --- ĐIỀU CHỈNH TỌA ĐỘ AN TOÀN HƠN ---
        # Top: 0.92 (Lấy cao hơn một chút để không bị mất đầu số)
        ratio_top = 0.92 
        ratio_left = 0.55
        
        rel_top = int(h_img * ratio_top)
        rel_bottom = h_img - 2 
        rel_left = int(card_w * ratio_left)
        rel_right = int(card_w * 0.98) 

        results = []
        debug_images = [] 

        for i in range(3):
            card_x_start = int(i * card_w)
            
            box_left = card_x_start + rel_left
            box_top = rel_top
            box_right = card_x_start + rel_right
            box_bottom = rel_bottom

            # 1. Cắt ảnh
            crop = img.crop((box_left, box_top, box_right, box_bottom))

            # --- XỬ LÝ ẢNH (FIX LỖI TRẮNG BÓC) ---
            
            # A. Phóng to
            crop = crop.resize((crop.width * 5, crop.height * 5), Image.Resampling.LANCZOS)
            
            # B. Chuyển xám
            crop = crop.convert('L')
            
            # C. Đảo màu (QUAN TRỌNG)
            # Thẻ Karuta số màu trắng nền đen.
            # Ta đảo thành: Số màu đen, nền trắng.
            crop = ImageOps.invert(crop)
            
            # D. Tự động cân bằng sáng (Thay vì xóa trắng)
            crop = ImageOps.autocontrast(crop)
            
            # E. Tăng độ đậm nhạt lên gấp 3 lần để chữ đen rõ hơn
            enhancer = ImageEnhance.Contrast(crop)
            crop = enhancer.enhance(3.0) 
            
            # (ĐÃ BỎ dòng crop.point... gây ra lỗi ảnh trắng)

            # Lưu ảnh debug
            img_byte_arr = io.BytesIO()
            crop.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            debug_images.append(discord.File(img_byte_arr, filename=f"debug_{i+1}.png"))

            # 2. OCR
            custom_config = r"--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789-"
            raw_text = pytesseract.image_to_string(crop, config=custom_config).strip()
            
            final_num = extract_print_number(raw_text)
            results.append(final_num)
            print(f"  [Card {i+1}] Raw: '{raw_text}' -> Final: '{final_num}'")

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
    if not message.attachments[0].content_type.startswith('image/'): return

    try:
        response = requests.get(message.attachments[0].url)
        numbers, debug_imgs = await get_print_numbers_from_image(response.content)

        if numbers:
            reply_text = ""
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            for i, num in enumerate(numbers):
                reply_text += f"▪️ {emojis[i]} | **#{num}**\n"
            
            await message.reply(content=reply_text, files=debug_imgs)

    except Exception as e:
        print(f"❌ Lỗi: {e}")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
