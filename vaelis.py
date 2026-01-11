# main.py - Phiên bản FINAL V3 (High Threshold + Smart Regex)

import discord
from discord.ext import commands
import os
import re
import requests
import io
from PIL import Image, ImageOps, ImageDraw, ImageFilter
from dotenv import load_dotenv
import threading
from flask import Flask
import asyncio
import pytesseract

# --- SERVER GIỮ BOT ONLINE ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot OCR Karuta V3 đang chạy."
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
    Logic thông minh: Ưu tiên tìm pattern 'Print - Edition'
    Ví dụ: '18013 · 2' hoặc '18013-2' -> Lấy 18013
    """
    if not text: return "???"
    
    # Bước 1: Thay thế các ký tự nhiễu thường gặp của dấu gạch ngang
    # Đôi khi OCR đọc dấu - thành dấu ngã ~, dấu chấm ., hoặc dấu cách
    cleaned_text = re.sub(r'[~—_.,]', '-', text) 

    # Bước 2: Tìm pattern "Số - Số" (Print - Edition)
    # (\d+) : Nhóm 1 (Số Print)
    # \s*[-]\s* : Dấu gạch (có thể có khoảng trắng)
    # \d+ : Số Edition
    match = re.search(r'(\d+)\s*[-]\s*\d+', cleaned_text)
    if match:
        return match.group(1) # Trả về nhóm 1 (Số Print)

    # Bước 3: Nếu không thấy dấu gạch, dùng logic cũ (tìm số dài nhất)
    # Nhưng loại bỏ các số quá dài vô lý (trên 7 chữ số thường là do dính chùm)
    numbers = re.findall(r'\d+', text)
    if numbers:
        # Lọc bỏ số > 7 chữ số (Karuta print hiện tại chưa đến hàng chục triệu)
        valid_numbers = [n for n in numbers if len(n) < 8]
        if valid_numbers:
            valid_numbers.sort(key=len, reverse=True)
            return valid_numbers[0]
            
    return "???"

async def get_print_numbers_from_image(image_bytes):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w_img, h_img = img.size
        
        debug_draw_img = img.copy()
        draw = ImageDraw.Draw(debug_draw_img)

        card_w = w_img / 3
        
        # --- CẤU HÌNH VÙNG CẮT (TINH CHỈNH MỚI) ---
        # Thu hẹp chiều dọc lại một chút để cắt bớt viền khung trên/dưới
        ratio_top = 0.90      # Tăng lên (cắt thấp hơn) để né viền trên
        ratio_bottom = 0.97   # Giảm xuống (cắt cao hơn) để né viền dưới
        
        # Giữ nguyên chiều ngang 0.5 để né họa tiết bên trái
        ratio_left = 0.50     
        ratio_right = 0.96

        rel_top = int(h_img * ratio_top)
        rel_bottom = int(h_img * ratio_bottom)

        results = []
        cropped_images = []

        for i in range(3):
            card_x_start = int(i * card_w)
            
            rel_left_px = int(card_w * ratio_left)
            rel_right_px = int(card_w * ratio_right)
            
            box_left = card_x_start + rel_left_px
            box_top = rel_top
            box_right = card_x_start + rel_right_px
            box_bottom = rel_bottom

            draw.rectangle([box_left, box_top, box_right, box_bottom], outline="red", width=3)
            crop = img.crop((box_left, box_top, box_right, box_bottom))

            # --- XỬ LÝ ẢNH (QUAN TRỌNG) ---
            crop = crop.resize((crop.width * 5, crop.height * 5), Image.Resampling.LANCZOS)
            crop = crop.convert('L') 
            
            # THRESHOLDING CAO HƠN: 
            # Tăng từ 110 lên 165. 
            # Lý do: Số Print màu trắng tinh (255). Khung xám chỉ khoảng 120-150.
            # Đặt 165 sẽ biến khung xám thành màu Đen (mất tích), chỉ còn lại số.
            threshold_val = 165 
            crop = crop.point(lambda p: 255 if p > threshold_val else 0)
            
            # Đảo màu (Chữ đen nền trắng)
            crop = ImageOps.invert(crop)

            # Padding (Viền trắng)
            crop = ImageOps.expand(crop, border=20, fill='white')

            img_byte_arr = io.BytesIO()
            crop.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            cropped_images.append(discord.File(img_byte_arr, filename=f"debug_crop_{i+1}.png"))

            # --- OCR ---
            # Thêm ký tự '·' vào whitelist vì một số thẻ dùng dấu chấm giữa
            custom_config = r"--psm 7 --oem 1 -c tessedit_char_whitelist=0123456789-·" 
            
            raw_text = pytesseract.image_to_string(crop, config=custom_config).strip()
            final_num = extract_number_with_regex(raw_text)
            
            results.append(final_num)
            print(f"  [Card {i+1}] OCR Raw: '{raw_text}' -> Result: '{final_num}'")

        full_debug_byte = io.BytesIO()
        debug_draw_img.save(full_debug_byte, format='PNG')
        full_debug_byte.seek(0)
        debug_file = discord.File(full_debug_byte, filename="DEBUG_FULL.png")

        return results, debug_file, cropped_images

    except Exception as e:
        print(f"Lỗi xử lý ảnh: {e}")
        return [], None, []

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
    print("🔎 Phát hiện ảnh Karuta, bắt đầu quét...")

    try:
        response = requests.get(message.attachments[0].url)
        image_bytes = response.content
        
        numbers, debug_full, debug_crops = await get_print_numbers_from_image(image_bytes)

        if numbers:
            reply_lines = []
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            
            for i, num in enumerate(numbers):
                if num == "???":
                    reply_lines.append(f"▪️ {emojis[i]} | ⚠️ Lỗi")
                else:
                    reply_lines.append(f"▪️ {emojis[i]} | **#{num}**")
            
            reply_text = "\n".join(reply_lines)
            
            # Gửi tất cả ảnh debug để dễ kiểm tra
            all_files = [debug_full] + debug_crops
            
            await message.reply(content=reply_text, files=all_files)
            print("✅ Đã gửi kết quả.")

    except Exception as e:
        print(f"❌ Lỗi Bot: {e}")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
    else:
        print("❌ LỖI: Chưa set DISCORD_TOKEN")
