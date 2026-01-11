# main.py - Phiên bản FIX PRINT READING (Thresholding + Whitelist)

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

# --- SERVER GIỮ BOT ONLINE (Cho Render/Heroku) ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot OCR Karuta đang chạy tốt."
def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264

# LƯU Ý: Nếu chạy trên Windows (Local), hãy bỏ comment dòng dưới và trỏ đúng đường dẫn
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def extract_number_with_regex(text):
    """
    Lọc lấy số print từ chuỗi OCR.
    Hỗ trợ các dạng: '#1234', '1234-1', '1234 · 1'
    """
    if not text: return "???"
    
    # Xóa tất cả các ký tự không phải số và gạch ngang để sạch sẽ
    # Giữ lại số và dấu - (ví dụ 1234-2)
    clean_text = re.sub(r'[^\d-]', ' ', text)
    
    # Tìm các cụm số
    numbers = re.findall(r'\d+', clean_text)
    
    if numbers:
        # Logic: Số print thường là số dài nhất tìm được (vd: 79872 > 1)
        # Sắp xếp theo độ dài giảm dần
        numbers.sort(key=len, reverse=True)
        return numbers[0]
        
    return "???"

async def get_print_numbers_from_image(image_bytes):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w_img, h_img = img.size
        
        # Ảnh để vẽ khung debug
        debug_draw_img = img.copy()
        draw = ImageDraw.Draw(debug_draw_img)

        card_w = w_img / 3
        
        # --- CẤU HÌNH VÙNG CẮT (ĐÃ CHỈNH SỬA) ---
        # Chỉ lấy phần đen dưới cùng chứa số. 
        # Né tên Series ở phía trên.
        ratio_top = 0.88      
        ratio_bottom = 0.98   
        ratio_left = 0.15     
        ratio_right = 0.95

        rel_top = int(h_img * ratio_top)
        rel_bottom = int(h_img * ratio_bottom)

        results = []
        cropped_images = [] # Danh sách ảnh crop (để gửi debug nếu cần)

        for i in range(3):
            card_x_start = int(i * card_w)
            
            rel_left_px = int(card_w * ratio_left)
            rel_right_px = int(card_w * ratio_right)
            
            box_left = card_x_start + rel_left_px
            box_top = rel_top
            box_right = card_x_start + rel_right_px
            box_bottom = rel_bottom

            # 1. Vẽ khung đỏ debug
            draw.rectangle([box_left, box_top, box_right, box_bottom], outline="red", width=3)

            # 2. Cắt ảnh
            crop = img.crop((box_left, box_top, box_right, box_bottom))

            # --- XỬ LÝ ẢNH NÂNG CAO (PRE-PROCESSING) ---
            # Resize to gấp 4 lần
            crop = crop.resize((crop.width * 4, crop.height * 4), Image.Resampling.LANCZOS)
            
            # Chuyển sang thang xám
            crop = crop.convert('L') 
            
            # THRESHOLDING (Quan trọng): Biến ảnh thành nhị phân (chỉ đen và trắng)
            # Mẹo: Số print màu trắng trên nền tối.
            # Ta lọc các điểm sáng (>110) thành trắng (255), còn lại thành đen (0).
            threshold_val = 110 
            crop = crop.point(lambda p: 255 if p > threshold_val else 0)
            
            # Đảo ngược màu: Tesseract thích CHỮ ĐEN trên NỀN TRẮNG
            crop = ImageOps.invert(crop)

            # Thêm viền trắng bao quanh để số không dính mép
            crop = ImageOps.expand(crop, border=20, fill='white')

            # Lưu ảnh crop vào buffer (để gửi lên Discord xem debug)
            img_byte_arr = io.BytesIO()
            crop.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            cropped_images.append(discord.File(img_byte_arr, filename=f"debug_card_{i+1}.png"))

            # 3. OCR Config
            # --psm 7: Treat the image as a single text line.
            # -c tessedit_char_whitelist=... : Chỉ cho phép đọc số và gạch ngang.
            custom_config = r"--psm 7 -c tessedit_char_whitelist=0123456789-" 
            
            raw_text = pytesseract.image_to_string(crop, config=custom_config).strip()
            final_num = extract_number_with_regex(raw_text)
            
            results.append(final_num)
            print(f"  [Card {i+1}] OCR Raw: '{raw_text}' -> Regex: '{final_num}'")

        # Lưu ảnh Debug toàn cảnh
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
    # Chỉ check tin nhắn từ Karuta Bot có ảnh
    if not (message.author.id == KARUTA_ID and message.attachments): return
    if not message.attachments[0].content_type.startswith('image/'): return

    print("\n" + "="*30)
    print("🔎 Phát hiện ảnh Karuta, đang quét...")

    try:
        response = requests.get(message.attachments[0].url)
        image_bytes = response.content
        
        # Lấy kết quả
        numbers, debug_full, debug_crops = await get_print_numbers_from_image(image_bytes)

        if numbers:
            reply_lines = []
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            
            for i, num in enumerate(numbers):
                # Format kết quả đẹp
                if num == "???":
                    reply_lines.append(f"▪️ {emojis[i]} | ⚠️ Không đọc được")
                else:
                    reply_lines.append(f"▪️ {emojis[i]} | **#{num}**")
            
            reply_text = "\n".join(reply_lines)
            
            # Gửi kết quả
            # files=[debug_full] -> Chỉ gửi ảnh debug khung đỏ.
            # Nếu muốn xem kỹ từng ảnh cắt, thêm `*debug_crops` vào list files.
            await message.reply(content=reply_text, files=[debug_full] + debug_crops)
            print("✅ Đã gửi kết quả.")

    except Exception as e:
        print(f"❌ Lỗi Bot: {e}")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
    else:
        print("❌ Chưa set DISCORD_TOKEN trong file .env!")
