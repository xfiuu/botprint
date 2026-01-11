# Sử dụng Python 3.10 trên nền Linux nhẹ
FROM python:3.10-slim

# Cài đặt các thư viện hệ thống cần thiết và Tesseract OCR
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    && rm -rf /var/lib/apt/lists/*

# Thiết lập thư mục làm việc
WORKDIR /app

# Copy toàn bộ code của bạn vào trong container
COPY . .

# Cài đặt các thư viện Python từ requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Chạy bot
CMD ["python", "vaelis.py"]
