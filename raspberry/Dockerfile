FROM python:3.13-slim

COPY pyproject.toml /src/
COPY scale_bot /src/scale_bot
RUN pip install --no-cache-dir /src

ENV PYTHONUNBUFFERED=1 \
    DATABASE=/data/measurements.sqlite3
WORKDIR /data

ENTRYPOINT ["scale-bot"]
CMD ["listen"]
