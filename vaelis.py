import discord
from discord.ext import commands
import os
import re
import aiohttp
import io
from PIL import Image, ImageOps
from dotenv import load_dotenv
import threading
from flask import Flask
import pytesseract
import asyncio
import concurrent.futures

# --- SERVER GIỮ BOT ONLINE ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot OCR Hybrid Speed & Accuracy."
def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264

# Nếu chạy trên Windows thì mở dòng dưới
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def filter_print_number(text):
    """Lọc số thông minh: Lấy chuỗi số dài nhất để tránh lấy nhầm edition"""
    if not text: return "???"
    # Chỉ giữ số và dấu gạch
    clean = re.sub(r'[^\d-]', '', text)
    # Tìm các cụm số
    matches = re.findall(r'\d+', clean)
    if matches:
        # Sắp xếp theo độ dài, lấy số dài nhất (thường là Print)
        matches.sort(key=len, reverse=True)
        return matches[0]
    return "???"

def process_single_card(img, index):
    """Hàm xử lý 1 thẻ độc lập (để chạy đa luồng)"""
    try:
        w_img, h_img = img.size
        card_w = w_img / 3
        
        # Tọa độ cắt chuẩn xác từ Vaelis 1
        ratio_top, ratio_bottom = 0.88, 0.94
        ratio_left, ratio_right = 0.54, 0.78
        
        card_x_start = int(index * card_w)
        box = (
            int(card_x_start + (card_w * ratio_left)), 
            int(h_img * ratio_top),                    
            int(card_x_start + (card_w * ratio_right)),
            int(h_img * ratio_bottom)                  
        )
        
        crop = img.crop(box)
        
        # --- XỬ LÝ ẢNH (Tối ưu) ---
        # Resize 3x (Cân bằng giữa nét và nhẹ) - BICUBIC tốt hơn BILINEAR
        crop = crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.BICUBIC)
        crop = crop.convert('L')
        
        # Threshold 110: Ngưỡng an toàn để chữ tách khỏi nền
        crop = crop.point(lambda p: 255 if p > 110 else 0)
        
        # Đảo màu (Chữ đen nền trắng) + Viền an toàn
        crop = ImageOps.invert(crop)
        crop = ImageOps.expand(crop, border=10, fill='white')
        
        # OCR config: Chỉ đọc số
        custom_config = r"--psm 7 -c tessedit_char_whitelist=0123456789-"
        raw_text = pytesseract.image_to_string(crop, config=custom_config)
        
        return filter_print_number(raw_text)
        
    except Exception:
        return "???"

async def solve_ocr_hybrid(image_bytes):
    """Chiến thuật: Chạy 3 luồng song song thay vì gộp ảnh"""
    img = Image.open(io.BytesIO(image_bytes))
    
    loop = asyncio.get_running_loop()
    
    # ThreadPoolExecutor giúp chạy 3 tác vụ OCR cùng lúc
    # Thời gian xử lý sẽ = thời gian của thẻ chậm nhất (thay vì tổng 3 thẻ)
    with concurrent.futures.ThreadPoolExecutor() as pool:
        tasks = [
            loop.run_in_executor(pool, process_single_card, img, 0),
            loop.run_in_executor(pool, process_single_card, img, 1),
            loop.run_in_executor(pool, process_single_card, img, 2)
        ]
        results = await asyncio.gather(*tasks)
        
    return results

# --- BOT DISCORD ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'🚀 HYBRID BOT READY: {bot.user}')

@bot.event
async def on_message(message):
    if message.author.id != KARUTA_ID: return
    if not message.attachments: return
    
    try:
        att = message.attachments[0]
        if "image" not in att.content_type: return

        # 1. Tải ảnh ASYNC (Siêu nhanh)
        async with aiohttp.ClientSession() as session:
            async with session.get(att.url) as resp:
                if resp.status != 200: return
                image_bytes = await resp.read()

        # 2. Xử lý Đa luồng (Nhanh & Chính xác)
        numbers = await solve_ocr_hybrid(image_bytes)

        if numbers:
            # Tạo Embed gọn đẹp
            embed = discord.Embed(color=0x36393f)
            description = ""
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            
            has_data = False
            for i, num in enumerate(numbers):
                if num not in ["???", ""]:
                    description += f"`{emojis[i]}` **#{num}** "
                    has_data = True
                else:
                    description += f"`{emojis[i]}` ...   "
            
            if has_data:
                embed.description = description
                await message.reply(embed=embed, mention_author=False)

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
    else:
        print("❌ Thiếu Token")
