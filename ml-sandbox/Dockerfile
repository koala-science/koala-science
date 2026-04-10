FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e "." fastapi uvicorn httpx

COPY . .

EXPOSE 8501

CMD ["python", "dashboard.py"]
