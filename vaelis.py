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
def home(): return "Bot OCR Hybrid Fix."
def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264

# QUAN TRỌNG: Mở dòng dưới nếu chạy trên máy tính Windows cá nhân
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def filter_print_number(text):
    if not text: return "???"
    clean = re.sub(r'[^\d-]', '', text)
    matches = re.findall(r'\d+', clean)
    if matches:
        matches.sort(key=len, reverse=True)
        return matches[0]
    return "???"

def process_single_card(image_bytes, index):
    """
    Mỗi luồng sẽ nhận data gốc và tự mở ảnh.
    An toàn hơn việc truyền 1 object Image cho nhiều luồng (tránh lỗi crash ngầm).
    """
    try:
        # Mở ảnh mới hoàn toàn trong luồng này
        img = Image.open(io.BytesIO(image_bytes))
        w_img, h_img = img.size
        
        # Tọa độ cắt (giữ nguyên setting chuẩn)
        card_w = w_img / 3
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
        
        # Xử lý ảnh: Resize 3x + Threshold
        crop = crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.BICUBIC)
        crop = crop.convert('L')
        crop = crop.point(lambda p: 255 if p > 110 else 0)
        crop = ImageOps.invert(crop)
        crop = ImageOps.expand(crop, border=10, fill='white')
        
        # OCR
        custom_config = r"--psm 7 -c tessedit_char_whitelist=0123456789-"
        raw_text = pytesseract.image_to_string(crop, config=custom_config)
        
        return filter_print_number(raw_text)
        
    except Exception as e:
        return f"Err: {str(e)}"

async def solve_ocr_hybrid(image_bytes):
    loop = asyncio.get_running_loop()
    
    # Chạy 3 luồng song song, mỗi luồng nhận image_bytes gốc
    with concurrent.futures.ThreadPoolExecutor() as pool:
        tasks = [
            loop.run_in_executor(pool, process_single_card, image_bytes, 0),
            loop.run_in_executor(pool, process_single_card, image_bytes, 1),
            loop.run_in_executor(pool, process_single_card, image_bytes, 2)
        ]
        results = await asyncio.gather(*tasks)
        
    return results

# --- BOT DISCORD ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'✅ BOT ĐÃ ONLINE: {bot.user}')

@bot.event
async def on_message(message):
    # --- DEBUG MODE: Tạm thời cho phép mọi người dùng để test ---
    # Nếu muốn chỉ Karuta dùng, hãy bỏ comment dòng dưới sau khi test xong:
    # if message.author.id != KARUTA_ID: return

    if not message.attachments: return
    
    try:
        att = message.attachments[0]
        if "image" not in att.content_type: return
        
        print(f"📥 Đang nhận ảnh từ {message.author.name}...")

        # Tải ảnh
        async with aiohttp.ClientSession() as session:
            async with session.get(att.url) as resp:
                if resp.status != 200:
                    await message.channel.send("❌ Không tải được ảnh từ Discord.")
                    return
                image_bytes = await resp.read()

        # Xử lý
        numbers = await solve_ocr_hybrid(image_bytes)
        
        # In ra console để kiểm tra
        print(f"📊 Kết quả OCR: {numbers}")

        # Gửi kết quả
        embed = discord.Embed(color=0x36393f)
        description = ""
        emojis = ["1️⃣", "2️⃣", "3️⃣"]
        
        has_valid_number = False
        for i, num in enumerate(numbers):
            if "Err" in num:
                description += f"`{emojis[i]}` ⚠️ Lỗi OCR\n"
            elif num in ["???", ""]:
                description += f"`{emojis[i]}` ...\n"
            else:
                description += f"`{emojis[i]}` **#{num}**\n"
                has_valid_number = True
        
        # Nếu đọc được ít nhất 1 số thì gửi, hoặc gửi báo lỗi nếu muốn
        if has_valid_number or "Err" in str(numbers):
            embed.description = description
            embed.set_footer(text="Hybrid Speed Mode")
            await message.reply(embed=embed, mention_author=False)
        else:
             print("⚠️ Không tìm thấy số nào rõ ràng.")

    except Exception as e:
        print(f"❌ LỖI NGHIÊM TRỌNG: {e}")
        # Báo lỗi thẳng vào chat để biết đường sửa
        await message.channel.send(f"⚠️ Bot gặp lỗi: `{e}`")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
    else:
        print("❌ Thiếu Token")
