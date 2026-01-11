# main.py - Phiên bản BALANCED FIX (Cắt chuẩn vị trí số Print)

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

# --- SERVER GIỮ BOT ONLINE (Dành cho Render/Heroku) ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot OCR Karuta đang chạy ổn định."
def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264

# LƯU Ý: Nếu chạy trên máy cá nhân (Windows), hãy bỏ comment dòng dưới và trỏ đúng đường dẫn
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def extract_number_with_regex(text):
    """
    Lọc lấy số print từ chuỗi OCR.
    Hỗ trợ các dạng: '7752-5', '42764 · 2'
    """
    if not text: return "???"
    
    # 1. Chỉ giữ lại số và dấu gạch ngang (loại bỏ chữ cái rác)
    clean_text = re.sub(r'[^\d-]', ' ', text)
    
    # 2. Tìm tất cả các cụm số
    numbers = re.findall(r'\d+', clean_text)
    
    if numbers:
        # Mẹo: Số Print thường là chuỗi số dài nhất tìm được (để tránh lấy nhầm số edition '1' hay '2')
        numbers.sort(key=len, reverse=True)
        return numbers[0]
        
    return "???"

async def get_print_numbers_from_image(image_bytes):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w_img, h_img = img.size
        
        # Tạo ảnh debug (để vẽ khung đỏ)
        debug_draw_img = img.copy()
        draw = ImageDraw.Draw(debug_draw_img)

        card_w = w_img / 3
        
        # --- CẤU HÌNH VÙNG CẮT (ĐÃ CHỈNH LẠI CHUẨN) ---
        # ratio_top: 0.89 -> Lấy cao hơn xíu để không mất đầu số
        # ratio_left: 0.55 -> Lấy từ gần giữa thẻ (bao trọn số Print)
        # ratio_right: 0.95 -> Không lấy sát mép phải quá (tránh rác)
        
        ratio_top = 0.87
        ratio_bottom = 0.94   
        ratio_left = 0.54     
        ratio_right = 0.80

        rel_top = int(h_img * ratio_top)
        rel_bottom = int(h_img * ratio_bottom)

        results = []
        cropped_images = [] # Danh sách ảnh cắt nhỏ để gửi debug

        for i in range(3):
            card_x_start = int(i * card_w)
            
            rel_left_px = int(card_w * ratio_left)
            rel_right_px = int(card_w * ratio_right)
            
            box_left = card_x_start + rel_left_px
            box_top = rel_top
            box_right = card_x_start + rel_right_px
            box_bottom = rel_bottom

            # 1. Vẽ khung đỏ lên ảnh debug tổng
            draw.rectangle([box_left, box_top, box_right, box_bottom], outline="red", width=3)

            # 2. Cắt ảnh con
            crop = img.crop((box_left, box_top, box_right, box_bottom))

            # --- XỬ LÝ ẢNH (PRE-PROCESSING) ---
            # Resize to gấp 4 để số rõ nét
            crop = crop.resize((crop.width * 4, crop.height * 4), Image.Resampling.LANCZOS)
            
            # Chuyển sang thang xám
            crop = crop.convert('L') 
            
            # THRESHOLDING: Biến ảnh thành đen trắng tuyệt đối
            # Ngưỡng 100: Giảm nhẹ để nét chữ dày hơn
            threshold_val = 100
            crop = crop.point(lambda p: 255 if p > threshold_val else 0)
            
            # Đảo màu: Để thành Chữ Đen trên Nền Trắng (Tesseract thích cái này nhất)
            crop = ImageOps.invert(crop)

            # Thêm viền trắng (padding) để số không bị dính sát mép ảnh
            crop = ImageOps.expand(crop, border=20, fill='white')

            # Lưu ảnh crop vào bộ nhớ để gửi lên Discord (Debug visual)
            img_byte_arr = io.BytesIO()
            crop.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            cropped_images.append(discord.File(img_byte_arr, filename=f"debug_crop_{i+1}.png"))

            # 3. OCR Config
            # --psm 7: Treat image as a single text line (Đọc 1 dòng duy nhất)
            # --oem 1: Neural nets engine (thường chính xác hơn)
            # whitelist: Chỉ cho phép đọc số và dấu gạch ngang
            custom_config = r"--psm 7 --oem 1 -c tessedit_char_whitelist=0123456789-" 
            
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
    # Chỉ xử lý tin nhắn từ Karuta có ảnh đính kèm
    if not (message.author.id == KARUTA_ID and message.attachments): return
    if not message.attachments[0].content_type.startswith('image/'): return

    print("\n" + "="*30)
    print("🔎 Phát hiện ảnh Karuta, bắt đầu quét...")

    try:
        response = requests.get(message.attachments[0].url)
        image_bytes = response.content
        
        # Gọi hàm xử lý
        numbers, debug_full, debug_crops = await get_print_numbers_from_image(image_bytes)

        if numbers:
            reply_lines = []
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            
            for i, num in enumerate(numbers):
                if num == "???":
                    reply_lines.append(f"▪️ {emojis[i]} | ⚠️ Không đọc được")
                else:
                    reply_lines.append(f"▪️ {emojis[i]} | **#{num}**")
            
            reply_text = "\n".join(reply_lines)
            
            # Gửi kết quả kèm ảnh debug
            # debug_full: Ảnh to có khung đỏ
            # debug_crops: 3 ảnh nhỏ đen trắng (để bạn kiểm tra xem bot nhìn thấy gì)
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
        print("❌ LỖI: Chưa set DISCORD_TOKEN trong file .env")





