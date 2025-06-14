📦 Сервис Управления Заказами (Паттерн Saga)
Сервис реализует распределённую транзакцию через паттерн Saga с использованием асинхронного взаимодействия через RabbitMQ и хранения состояния в MongoDB .

🧠 Основные принципы
- Реализация Saga orchestration — централизованное управление шагами.
- Использование RabbitMQ для обмена сообщениями между микросервисами.
- Хранение состояния саги в MongoDB .
- Использование FastStream и FastAPI для асинхронных обработчиков и HTTP API.

📦 Технологии
- Python 3.10+
- FastAPI
- FastStream + RabbitMQ
- Motor (асинхронный драйвер MongoDB)
- Docker / Docker Compose

🛠 Архитектура Saga
Состояние саги (SagaState)


```python
{
    "correlation_id": str,
    "order_id": str,
    "status": "pending | completed | failed",
    "steps": ["inventory_reserved", "payment_processed", ...]
}
```
Этапы саги:
- saga.start → Резервирование товара (inventory_reserved)
- saga.inventory.reserved → Обработка оплаты (payment)
- saga.notify → Уведомление пользователя (notified)

При ошибке: откат всех шагов

🐳 Как запустить
1. Клонируйте репозиторий:
```sh
git clone https://github.com/elbrus-56/saga_service
cd saga-service
docker-compose up -d
```

Сервис будет доступен по адресу:
🔗 http://localhost:8000

Документация Swagger:
🔗 http://localhost:8000/docs


📁 Конфигурация
Настройки берутся из переменных окружения (.env или configs/settings.py):

rabbit_uri — URI подключения к RabbitMQ
mongo_uri — URI подключения к MongoDB

🧹 Компенсация (Rollback)
Если происходит ошибка на любом этапе:

- Публикуется событие в saga.errors
- Запускается компенсирующая логика (saga.compensation)
- Откатывается состояние (inventory, payment и т.д.)
- Сага помечается как FAILED
- Заказ отменяется и статус ставится как CANCELLED
