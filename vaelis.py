import discord
from discord.ext import commands
import os
import re
import aiohttp
import io
from PIL import Image, ImageOps, ImageChops, ImageFilter 
from dotenv import load_dotenv
import threading
from flask import Flask
import pytesseract
import asyncio
import functools
from collections import deque

# --- SERVER ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot OCR HighRes Mode."
def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- CONFIG ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264 
processed_cache = deque(maxlen=50)

def solve_ocr_fast(image_bytes, return_image=False):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w_img, h_img = img.size
        
        card_w = w_img / 3
        
        # Tọa độ cắt (Giữ nguyên vì đã chuẩn)
        ratio_top, ratio_bottom = 0.88, 0.94
        ratio_left, ratio_right = 0.54, 0.78 

        crops = []
        for i in range(3):
            # 1. CẮT
            card_x_start = int(i * card_w)
            box = (
                int(card_x_start + (card_w * ratio_left)), 
                int(h_img * ratio_top),                    
                int(card_x_start + (card_w * ratio_right)),
                int(h_img * ratio_bottom)                  
            )
            crop = img.crop(box)

            # 2. XỬ LÝ (TINH CHỈNH MỚI)
            # --- UPDATE 1: Resize cực lớn (x5) ---
            # Dùng LANCZOS để giữ nét tốt hơn Bilinear khi phóng to
            crop = crop.resize((crop.width * 5, crop.height * 5), Image.Resampling.LANCZOS)
            
            # --- Tách nền (Red - Blue) ---
            if crop.mode != 'RGB': crop = crop.convert('RGB')
            r, g, b = crop.split()
            processed = ImageChops.subtract(r, b)
            
            # Threshold
            processed = processed.point(lambda p: 255 if p > 50 else 0)
            processed = ImageOps.invert(processed)
            
            # --- UPDATE 2: Làm đậm vừa phải ---
            # Vẫn dùng MinFilter(3) nhưng trên ảnh to gấp 5 lần
            # -> Nét chữ dày lên nhưng lỗ số 8 vẫn thoáng
            processed = processed.filter(ImageFilter.MinFilter(3))

            # Thêm viền trắng
            processed = ImageOps.expand(processed, border=50, fill='white')
            
            crops.append(processed)

        # 3. GỘP DỌC
        w_c, h_c = crops[0].size
        total_h = (h_c * 3) + 50
        
        final_img = Image.new('L', (w_c, total_h), color=255)
        
        final_img.paste(crops[0], (0, 0))
        final_img.paste(crops[1], (0, h_c + 20))
        final_img.paste(crops[2], (0, (h_c * 2) + 40))

        if return_image:
            return final_img

        # 4. OCR
        custom_config = r"--psm 6 -c tessedit_char_whitelist=0123456789-·."
        text = pytesseract.image_to_string(final_img, config=custom_config)
        
        matches = re.findall(r'\d+(?:[-·\.]\d+)?', text)
        
        results = []
        for i in range(3):
            if i < len(matches):
                clean_num = matches[i].replace('·', '-').replace('.', '-')
                results.append(clean_num)
            else:
                results.append("???")
        
        return results

    except Exception as e:
        print(f"Error: {e}")
        return None

# --- BOT COMMANDS ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'✨ BOT FIX 8 vs 0 READY: {bot.user}')

@bot.command()
async def ocr(ctx):
    """Lệnh test xem ảnh bot nhìn thấy thế nào"""
    target_url = None
    if ctx.message.attachments:
        target_url = ctx.message.attachments[0].url
    elif ctx.message.reference:
        original_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        if original_msg.attachments:
            target_url = original_msg.attachments[0].url

    if not target_url:
        await ctx.send("❌ Vui lòng gửi/reply ảnh.")
        return

    async with ctx.typing():
        async with aiohttp.ClientSession() as session:
            async with session.get(target_url) as resp:
                image_bytes = await resp.read()

        loop = asyncio.get_running_loop()
        processed_img = await loop.run_in_executor(
            None, 
            functools.partial(solve_ocr_fast, image_bytes, return_image=True)
        )

        if processed_img:
            with io.BytesIO() as image_binary:
                processed_img.save(image_binary, 'PNG')
                image_binary.seek(0)
                await ctx.send(
                    content="**Ảnh High-Res (Đã fix lỗi 8 thành 0):**",
                    file=discord.File(fp=image_binary, filename='fix_8_0.png')
                )

@bot.event
async def on_message(message):
    await bot.process_commands(message)
    if message.author.id != KARUTA_ID: return
    if not message.attachments: return
    if message.id in processed_cache: return
    processed_cache.append(message.id)

    try:
        att = message.attachments[0]
        if "image" not in att.content_type: return

        async with aiohttp.ClientSession() as session:
            async with session.get(att.url) as resp:
                image_bytes = await resp.read()

        loop = asyncio.get_running_loop()
        numbers = await loop.run_in_executor(None, functools.partial(solve_ocr_fast, image_bytes))

        if numbers:
            embed = discord.Embed(color=0x36393f, timestamp=message.created_at)
            embed.set_footer(text="⚡ High Accuracy") 
            description = ""
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            for i, num in enumerate(numbers):
                status = f"**#{num}**" if num not in ["???", "Err"] else "⚠️ **Unknown**"
                description += f"▪️ {emojis[i]} | {status}\n"
            
            embed.description = description
            await message.reply(embed=embed, mention_author=False)
    except: pass

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
