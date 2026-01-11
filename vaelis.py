# main.py - Phiên bản VISUAL DEBUG + REGEX FINDER

import discord
from discord.ext import commands
import os
import re
import requests
import io
from PIL import Image, ImageOps, ImageStat, ImageEnhance, ImageDraw
from dotenv import load_dotenv
import threading
from flask import Flask
import asyncio
import pytesseract

# --- SERVER GIỮ BOT ONLINE ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot OCR Debug đang chạy."
def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264

# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def extract_number_with_regex(text):
    """
    Dùng Regex để tìm số Print trong đống văn bản hỗn độn.
    Ưu tiên tìm chuỗi có dạng '#12345'.
    Nếu không thấy dấu #, tìm chuỗi số dài nhất ở cuối câu.
    """
    if not text: return "???"
    
    # Bước 1: Tìm chuỗi dạng #12345 (có dấu # ở trước)
    match_hash = re.search(r'#\s*(\d+)', text)
    if match_hash:
        return match_hash.group(1)
    
    # Bước 2: Nếu không có dấu #, tìm các nhóm số (vd: 28183-2 -> lấy 28183)
    # Lấy tất cả các nhóm số
    numbers = re.findall(r'\d+', text)
    if numbers:
        # Thường số print là số có nhiều chữ số nhất hoặc nằm cuối cùng
        # Lọc các số quá ngắn (dưới 2 chữ số) có thể là rác
        valid_numbers = [n for n in numbers if len(n) >= 2]
        if valid_numbers:
            return valid_numbers[-1] # Lấy số cuối cùng tìm thấy
        return numbers[-1]
        
    return "???"

async def get_print_numbers_from_image(image_bytes):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w_img, h_img = img.size
        
        # Tạo một bản sao của ảnh để VẼ KHUNG ĐỎ (Debug)
        debug_draw_img = img.copy()
        draw = ImageDraw.Draw(debug_draw_img)

        # Tính toán kích thước 1 thẻ
        card_w = w_img / 3
        
        # --- CHIẾN THUẬT CẮT VÙNG RỘNG (SAFE ZONE) ---
        # Thay vì cắt sát sạt, ta cắt rộng ra để đảm bảo không bị trượt.
        # Top: Lấy từ 75% chiều dọc trở xuống (Bao gồm cả tên Series và đáy thẻ)
        # Left: Lấy từ 40% chiều ngang thẻ (Bên phải)
        
        ratio_top = 0.75 
        ratio_left = 0.40
        
        rel_top = int(h_img * ratio_top)
        rel_bottom = h_img
        rel_left = int(card_w * ratio_left)
        rel_right = int(card_w * 0.99) # Sát mép phải

        results = []
        cropped_images = [] # Ảnh cắt nhỏ để OCR

        for i in range(3):
            card_x_start = int(i * card_w)
            
            box_left = card_x_start + rel_left
            box_top = rel_top
            box_right = card_x_start + rel_right
            box_bottom = rel_bottom

            # 1. Vẽ khung đỏ lên ảnh Debug để bạn kiểm tra
            draw.rectangle([box_left, box_top, box_right, box_bottom], outline="red", width=5)

            # 2. Cắt ảnh để xử lý OCR
            crop = img.crop((box_left, box_top, box_right, box_bottom))

            # --- XỬ LÝ ẢNH ---
            crop = crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.LANCZOS)
            crop = crop.convert('L')
            
            # Tự động đảo màu nếu nền đen
            stat = ImageStat.Stat(crop)
            if stat.mean[0] < 128: 
                crop = ImageOps.invert(crop)

            enhancer = ImageEnhance.Contrast(crop)
            crop = enhancer.enhance(2.0)
            
            # Lưu ảnh crop (nếu muốn xem chi tiết vùng cắt)
            img_byte_arr = io.BytesIO()
            crop.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            cropped_images.append(discord.File(img_byte_arr, filename=f"crop_{i+1}.png"))

            # 3. OCR (Đọc cả khối văn bản)
            # --psm 6: Assume a single uniform block of text.
            custom_config = r"--psm 6 --oem 3" 
            raw_text = pytesseract.image_to_string(crop, config=custom_config).strip()
            
            # Dùng Regex để mò số trong đống chữ vừa đọc
            final_num = extract_number_with_regex(raw_text)
            results.append(final_num)
            print(f"  [Card {i+1}] Raw OCR: '{raw_text}' -> Regex Found: '{final_num}'")

        # Lưu ảnh Debug tổng thể (có khung đỏ)
        full_debug_byte = io.BytesIO()
        debug_draw_img.save(full_debug_byte, format='PNG')
        full_debug_byte.seek(0)
        debug_file = discord.File(full_debug_byte, filename="DEBUG_RED_BOX.png")

        return results, debug_file

    except Exception as e:
        print(f"Lỗi: {e}")
        return [], None

# --- BOT DISCORD ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'✅ Bot Online: {bot.user}')

@bot.event
async def on_message(message):
    if not (message.author.id == KARUTA_ID and message.attachments): return
    if not message.attachments[0].content_type.startswith('image/'): return

    print("\n" + "="*30)
    print("🔎 Đang xử lý ảnh Karuta...")

    try:
        response = requests.get(message.attachments[0].url)
        image_bytes = response.content
        
        # Hàm trả về: Danh sách số VÀ Ảnh Debug toàn cảnh
        numbers, debug_img_file = await get_print_numbers_from_image(image_bytes)

        if numbers:
            reply_lines = []
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            for i, num in enumerate(numbers):
                reply_lines.append(f"▪️ {emojis[i]} | **#{num}**")
            
            reply_text = "\n".join(reply_lines)
            
            # Gửi kết quả và ảnh Debug Khung Đỏ
            await message.reply(content=reply_text, file=debug_img_file)
            print("✅ Đã gửi kết quả.")

    except Exception as e:
        print(f"❌ Lỗi: {e}")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
