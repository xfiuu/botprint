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
def home(): return "Bot OCR Karuta Ultimate Mode."
def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264

# Bộ nhớ đệm chống Spam (lưu 100 tin nhắn gần nhất)
processed_messages = deque(maxlen=100)

# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# --- HÀM XỬ LÝ ẢNH CHUNG (Dùng cho cả Auto và lệnh !ocr) ---
def create_processed_image(img):
    """
    Hàm này thực hiện cắt, xử lý đen trắng và gộp ảnh.
    Trả về: Một tấm ảnh PIL (Stitched Image) đã sẵn sàng để đọc.
    """
    w_img, h_img = img.size
    card_w = w_img / 3
    
    # Tọa độ cắt
    ratio_top, ratio_bottom = 0.88, 0.94
    ratio_left, ratio_right = 0.54, 0.78 

    processed_crops = []
    
    for i in range(3):
        card_x_start = int(i * card_w)
        box = (
            int(card_x_start + (card_w * ratio_left)), 
            int(h_img * ratio_top),                    
            int(card_x_start + (card_w * ratio_right)),
            int(h_img * ratio_bottom)                  
        )
        crop = img.crop(box)

        # Xử lý ảnh (Filter)
        crop = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.BICUBIC)
        crop = crop.convert('L')
        enhancer = ImageEnhance.Contrast(crop)
        crop = enhancer.enhance(2.0)
        # Threshold: > 140 thành trắng, < 140 thành đen
        crop = crop.point(lambda p: 255 if p > 140 else 0)
        # Đảo màu thành chữ Đen nền Trắng
        crop = ImageOps.invert(crop)
        
        processed_crops.append(crop)

    # Gộp ảnh với khoảng cách lớn
    w_crop, h_crop = processed_crops[0].size
    gap = 100 
    total_width = (w_crop * 3) + (gap * 2)
    stitched_img = Image.new('L', (total_width, h_crop), color=255) # Nền trắng
    
    stitched_img.paste(processed_crops[0], (0, 0))
    stitched_img.paste(processed_crops[1], (w_crop + gap, 0))
    stitched_img.paste(processed_crops[2], ((w_crop + gap) * 2, 0))
    
    return stitched_img

def process_image_ultimate(image_bytes):
    """Hàm đọc số từ ảnh (Auto Farm)"""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        
        # Gọi hàm tạo ảnh đã xử lý ở trên
        stitched_img = create_processed_image(img)

        # OCR
        custom_config = r"--psm 6 -c tessedit_char_whitelist=0123456789-"
        text = pytesseract.image_to_string(stitched_img, config=custom_config)
        
        matches = re.findall(r'\d+(?:-\d+)?', text)
        results = []
        for i in range(3):
            if i < len(matches):
                results.append(matches[i])
            else:
                results.append("???")
        return results
    except Exception as e:
        print(f"Lỗi: {e}")
        return ["Err", "Err", "Err"]

def get_debug_image_bytes(image_bytes):
    """Hàm tạo ảnh debug để gửi lên Discord"""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        stitched_img = create_processed_image(img)
        
        # Lưu ảnh vào bộ nhớ đệm để gửi đi
        output_buffer = io.BytesIO()
        stitched_img.save(output_buffer, format='PNG')
        output_buffer.seek(0)
        return output_buffer
    except Exception as e:
        print(f"Lỗi debug ảnh: {e}")
        return None

# --- BOT DISCORD ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'🚀 Bot Online: {bot.user}')

# --- LỆNH !OCR ĐỂ SOI ẢNH ---
@bot.command()
async def ocr(ctx):
    # Kiểm tra xem user có reply tin nhắn nào không
    if not ctx.message.reference:
        await ctx.reply("⚠️ Hãy reply (trả lời) vào tin nhắn có ảnh cần soi!", mention_author=False)
        return

    # Lấy tin nhắn gốc được reply
    ref_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
    
    if not ref_message.attachments:
        await ctx.reply("⚠️ Tin nhắn bạn reply không có ảnh!", mention_author=False)
        return

    att = ref_message.attachments[0]
    if "image" not in att.content_type:
        await ctx.reply("⚠️ File đính kèm không phải là ảnh!", mention_author=False)
        return

    await ctx.typing() # Hiển thị "Bot is typing..."

    try:
        # Tải ảnh
        async with aiohttp.ClientSession() as session:
            async with session.get(att.url) as resp:
                if resp.status != 200: return
                image_bytes = await resp.read()

        # Tạo ảnh debug ở luồng phụ
        loop = asyncio.get_running_loop()
        debug_img_buffer = await loop.run_in_executor(None, functools.partial(get_debug_image_bytes, image_bytes))

        if debug_img_buffer:
            file = discord.File(debug_img_buffer, filename="debug_view.png")
            await ctx.reply("**Đây là những gì Bot nhìn thấy:**\n(Đã cắt, lọc nhiễu, đảo màu và gộp ảnh)", file=file, mention_author=False)
        else:
            await ctx.reply("❌ Lỗi khi xử lý ảnh debug.", mention_author=False)

    except Exception as e:
        await ctx.reply(f"❌ Lỗi: {e}", mention_author=False)

# --- AUTO SCAN ---
@bot.event
async def on_message(message):
    # Cần dòng này để lệnh !ocr hoạt động được
    await bot.process_commands(message)

    if message.author.id != KARUTA_ID or not message.attachments: return
    
    # Check chống spam
    if message.id in processed_messages: return
    processed_messages.append(message.id)

    att = message.attachments[0]
    if not att.content_type or "image" not in att.content_type: return

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(att.url) as resp:
                if resp.status != 200: return
                image_bytes = await resp.read()

        loop = asyncio.get_running_loop()
        numbers = await loop.run_in_executor(None, functools.partial(process_image_ultimate, image_bytes))

        if numbers:
            embed = discord.Embed(color=0x36393f, timestamp=message.created_at)
            embed.set_footer(text="⚡ Fast OCR") 
            description = ""
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            for i, num in enumerate(numbers):
                if num in ["???", "Err", ""]:
                    description += f"▪️ {emojis[i]} | ⚠️ **Unknown**\n"
                else:
                    description += f"▪️ {emojis[i]} | **#{num}**\n"
            embed.description = description
            await message.reply(embed=embed, mention_author=False)
            print(f"✅ Auto Result: {numbers}")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
    else:
        print("❌ Thiếu Token")
