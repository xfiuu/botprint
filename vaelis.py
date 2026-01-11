# main.py - Phiên bản V4: AUTO CLEAN BORDERS (Chống lệch + Xóa nhiễu)

import discord
from discord.ext import commands
import os
import re
import requests
import io
from PIL import Image, ImageOps, ImageDraw
from dotenv import load_dotenv
import threading
from flask import Flask
import pytesseract

# --- SERVER GIỮ BOT ONLINE ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot OCR Karuta V4 đang chạy."
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
    Logic: Tìm chuỗi dạng 'Print - Edition'.
    Nếu bị dính số rác ở đầu (vd: 718013-2), regex vẫn sẽ bắt đúng cụm 18013-2.
    """
    if not text: return "???"
    
    # 1. Dọn dẹp ký tự lạ, thay thế các dấu gạch/chấm lạ thành dấu '-' chuẩn
    cleaned_text = re.sub(r'[~—_.,]', '-', text)
    
    # 2. Regex bắt buộc phải tìm thấy pattern: Số + Dấu cách/gạch + Số
    # \b: Ranh giới từ (để tránh bắt dính chùm)
    # (\d{1,6}): Nhóm 1 - Số Print (từ 1 đến 6 chữ số)
    match = re.search(r'(\d{1,7})\s*[-]\s*\d+', cleaned_text)
    if match:
        return match.group(1)

    # 3. Fallback: Nếu không tìm thấy dấu gạch, tìm số đứng riêng lẻ
    # Lọc bỏ các số quá dài (>7 chữ số) vì đó thường là lỗi dính chùm
    numbers = re.findall(r'\d+', text)
    valid_numbers = [n for n in numbers if len(n) < 7 and len(n) > 1]
    
    if valid_numbers:
        # Lấy số dài nhất (ưu tiên Print hơn Edition)
        valid_numbers.sort(key=len, reverse=True)
        return valid_numbers[0]
            
    return "???"

def clean_border_noise(img_bw):
    """
    Hàm này vẽ đè màu trắng lên mép trên/dưới/trái để xóa viền khung.
    Giúp OCR không đọc nhầm viền thành số 7 hoặc 1.
    """
    draw = ImageDraw.Draw(img_bw)
    w, h = img_bw.size
    
    # 1. Xóa mép trên (Top Eraser) - Xóa 15% chiều cao từ trên xuống
    # Để loại bỏ các vệt đen của khung trên đầu số
    draw.rectangle([0, 0, w, int(h * 0.15)], fill=255) # 255 = Trắng
    
    # 2. Xóa mép dưới (Bottom Eraser) - Xóa 5% chiều cao từ dưới lên
    draw.rectangle([0, h - int(h * 0.05), w, h], fill=255)
    
    # 3. Xóa mép trái (Left Eraser) - Xóa 2% bên trái để an toàn
    draw.rectangle([0, 0, int(w * 0.02), h], fill=255)
    
    return img_bw

async def get_print_numbers_from_image(image_bytes):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w_img, h_img = img.size
        
        debug_draw_img = img.copy()
        draw = ImageDraw.Draw(debug_draw_img)

        card_w = w_img / 3
        
        # --- CẤU HÌNH VÙNG CẮT (ĐÃ NỚI RỘNG ĐỂ CHỐNG LỆCH) ---
        # ratio_top: 0.85 (Cao hơn cũ 0.88/0.90) -> Đảm bảo không bị mất đầu số.
        # ratio_left: 0.42 (Rộng hơn cũ 0.50) -> Đảm bảo số dài không bị mất đầu.
        ratio_top = 0.85      
        ratio_bottom = 0.98   
        ratio_left = 0.42     
        ratio_right = 0.97

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

            # Vẽ khung debug
            draw.rectangle([box_left, box_top, box_right, box_bottom], outline="red", width=3)
            crop = img.crop((box_left, box_top, box_right, box_bottom))

            # --- XỬ LÝ ẢNH ---
            crop = crop.resize((crop.width * 5, crop.height * 5), Image.Resampling.LANCZOS)
            crop = crop.convert('L') 
            
            # Thresholding: Tách nền
            threshold_val = 150 # Giảm nhẹ so với 165 để chữ không bị đứt nét
            crop = crop.point(lambda p: 255 if p > threshold_val else 0)
            
            # Đảo màu: Chữ đen nền trắng
            crop = ImageOps.invert(crop)
            
            # --- BƯỚC MỚI: TẨY XÓA THỦ CÔNG ---
            # Gọi hàm xóa các vệt đen ở mép trên/dưới
            crop = clean_border_noise(crop)

            # Thêm viền trắng an toàn
            crop = ImageOps.expand(crop, border=20, fill='white')

            img_byte_arr = io.BytesIO()
            crop.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            cropped_images.append(discord.File(img_byte_arr, filename=f"debug_clean_{i+1}.png"))

            # --- OCR ---
            custom_config = r"--psm 7 --oem 1 -c tessedit_char_whitelist=0123456789-·" 
            raw_text = pytesseract.image_to_string(crop, config=custom_config).strip()
            final_num = extract_number_with_regex(raw_text)
            
            results.append(final_num)
            print(f"  [Card {i+1}] OCR: '{raw_text}' -> Regex: '{final_num}'")

        full_debug_byte = io.BytesIO()
        debug_draw_img.save(full_debug_byte, format='PNG')
        full_debug_byte.seek(0)
        debug_file = discord.File(full_debug_byte, filename="DEBUG_FULL.png")

        return results, debug_file, cropped_images

    except Exception as e:
        print(f"Lỗi xử lý: {e}")
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
    print("🔎 Đang quét ảnh Karuta...")

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
            
            # Gửi ảnh debug để check
            all_files = [debug_full] + debug_crops
            
            await message.reply(content=reply_text, files=all_files)
            print("✅ Xong.")

    except Exception as e:
        print(f"❌ Lỗi Bot: {e}")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
    else:
        print("❌ LỖI: Chưa set DISCORD_TOKEN")
