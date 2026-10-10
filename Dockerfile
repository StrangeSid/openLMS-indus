# openLMS on Cloud Run. Listens on $PORT (Cloud Run injects it; default 8080
# for local `docker run`). --proxy-headers is required so login cookies are
# marked Secure and the CSRF guard sees the real https scheme behind proxies.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY openlms/ ./openlms/
COPY web/ ./web/

EXPOSE 8080

CMD ["sh", "-c", "uvicorn openlms.app:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers"]
