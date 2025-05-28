FROM python:3.12-slim

WORKDIR /app

# Аргумент для выбора сервиса
# ARG SERVICE_NAME

# Копируем зависимости сначала для кэширования
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Устанавливаем переменную окружения для выбора сервиса
# ENV SERVICE=${SERVICE_NAME}

# Запускаем соответствующий сервис

ENTRYPOINT ["sh", "-c", "uvicorn  ${SERVICE_NAME}:app --host 0.0.0.0 --port 80 "]
