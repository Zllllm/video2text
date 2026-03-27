FROM python:3.10-slim

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 输出目录
RUN mkdir -p /app/output

EXPOSE 8899

CMD ["python3", "app.py"]
