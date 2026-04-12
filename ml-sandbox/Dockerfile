FROM python:3.12-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir "." fastapi uvicorn httpx

EXPOSE 8501

CMD ["python", "dashboard.py"]
