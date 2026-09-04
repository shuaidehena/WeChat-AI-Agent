# LLM Gateway — 可在 Linux Docker 中运行（不依赖 Windows / 微信）
FROM python:3.10-slim

WORKDIR /app

# 安装依赖（层缓存：先复制 requirements）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY app.py .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
