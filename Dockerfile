FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY . .

# Создаем пользователя для запуска приложения
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Запускаем бота
CMD ["python", "bot.py"]