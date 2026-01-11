# main.py - Phiên bản V5: FIX CROP HEIGHT (Kéo vùng cắt lên cao + Whitelist mạnh)

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
def home(): return "Bot OCR Karuta V5 (Fix Crop) đang chạy."
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
    Tìm kiếm pattern: 'Số - Số'.
    Bỏ qua mọi rác (chữ cái, ký tự lạ) xung quanh.
    """
    if not text: return "???"
    
    # 1. Chuẩn hóa dấu phân cách
    cleaned_text = re.sub(r'[~—_.,|]', '-', text)
    
    # 2. Tìm chính xác cụm: Số + Dấu - + Số
    # Regex này rất mạnh: Nó sẽ tìm cụm số có gạch nối bất kể xung quanh là gì
    match = re.search(r'(\d{1,7})\s*[-]\s*\d+', cleaned_text)
    if match:
        return match.group(1)

    # 3. Fallback: Nếu không thấy dấu gạch, tìm số lớn nhất hợp lý
    numbers = re.findall(r'\d+', text)
    # Lọc số từ 2-7 chữ số (Bỏ số 1 chữ số vì dễ là rác do khung tranh)
    valid_numbers = [n for n in numbers if 1 < len(n) < 8]
    
    if valid_numbers:
        valid_numbers.sort(key=len, reverse=True)
        return valid_numbers[0]
            
    return "???"

def clean_border_noise(img_bw):
    """
    Xóa nhiễu viền trên và dưới sau khi cắt.
    Vì cắt cao (0.80) nên cần xóa mép trên mạnh tay hơn để bay mất chân chữ của tên Series (nếu dính).
    """
    draw = ImageDraw.Draw(img_bw)
    w, h = img_bw.size
    
    # Xóa 10% đỉnh ảnh (nơi có thể dính chân chữ của tên Series)
    draw.rectangle([0, 0, w, int(h * 0.10)], fill=255) 
    
    # Xóa 5% đáy ảnh (nơi dính viền khung dưới)
    draw.rectangle([0, h - int(h * 0.05), w, h], fill=255)
    
    # Xóa 2% bên trái
    draw.rectangle([0, 0, int(w * 0.02), h], fill=255)
    
    return img_bw

async def get_print_numbers_from_image(image_bytes):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w_img, h_img = img.size
        
        debug_draw_img = img.copy()
        draw = ImageDraw.Draw(debug_draw_img)

        card_w = w_img / 3
        
        # --- SỬA LỖI TẠI ĐÂY: DI CHUYỂN VÙNG CẮT LÊN CAO ---
        # ratio_top: 0.80 (Trước là 0.88/0.90 -> Quá thấp). 
        # Để 0.80 sẽ lấy rộng lên phía trên, chấp nhận dính chút tên Series nhưng ko mất số.
        ratio_top = 0.80      
        ratio_bottom = 0.98   
        
        # ratio_left: 0.50 (Lấy nửa phải). 
        # Print luôn nằm bên phải.
        ratio_left = 0.50     
        ratio_right = 0.98

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

            # Debug khung đỏ
            draw.rectangle([box_left, box_top, box_right, box_bottom], outline="red", width=3)
            crop = img.crop((box_left, box_top, box_right, box_bottom))

            # --- XỬ LÝ ẢNH ---
            crop = crop.resize((crop.width * 5, crop.height * 5), Image.Resampling.LANCZOS)
            crop = crop.convert('L') 
            
            # Thresholding
            threshold_val = 145 # Giảm nhẹ để số mảnh (thin font) cũng hiện rõ
            crop = crop.point(lambda p: 255 if p > threshold_val else 0)
            crop = ImageOps.invert(crop)
            
            # Xóa nhiễu viền/chữ thừa
            crop = clean_border_noise(crop)

            crop = ImageOps.expand(crop, border=20, fill='white')

            img_byte_arr = io.BytesIO()
            crop.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            cropped_images.append(discord.File(img_byte_arr, filename=f"crop_v5_{i+1}.png"))

            # --- OCR (WHITELIST QUAN TRỌNG) ---
            # Chỉ cho phép đọc số. Nếu dính chữ "Team" hay "Gundam", nó sẽ bị lờ đi.
            custom_config = r"--psm 7 --oem 1 -c tessedit_char_whitelist=0123456789-·" 
            
            raw_text = pytesseract.image_to_string(crop, config=custom_config).strip()
            final_num = extract_number_with_regex(raw_text)
            
            results.append(final_num)
            print(f"  [Card {i+1}] OCR: '{raw_text}' -> Regex: '{final_num}'")

        full_debug_byte = io.BytesIO()
        debug_draw_img.save(full_debug_byte, format='PNG')
        full_debug_byte.seek(0)
        debug_file = discord.File(full_debug_byte, filename="DEBUG_FULL_V5.png")

        return results, debug_file, cropped_images

    except Exception as e:
        print(f"Lỗi: {e}")
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
    print("🔎 Đang quét ảnh Karuta (V5)...")

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
            
            # Gửi debug file để kiểm tra xem đã cắt đủ đầu số chưa
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
