FROM python:3.12-slim

WORKDIR /app

# The verification check runs its agent as this uid rather than as root. The
# agent reads text written by anyone on the platform and has a shell, and a
# non-root uid cannot read root's /proc/1/environ — where the container's
# secrets sit, out of reach of anything the process itself can scrub.
RUN useradd --system --uid 1001 --no-create-home verification-agent

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run alembic migrations and then start the server
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4"]
