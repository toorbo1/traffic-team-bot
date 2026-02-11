FROM python:3.11-slim

WORKDIR /app

# Сначала копируем только requirements
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальной код
COPY . .

# Запускаем бота
CMD ["python", "bot.py"]