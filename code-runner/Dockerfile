FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app


COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


COPY app ./app
COPY agent /app/agent

# ENV AGENT_PATH=/app/agent

# RUN useradd -m serviceuser
# USER serviceuser

CMD ["faststream", "run", "app.main:app"]
