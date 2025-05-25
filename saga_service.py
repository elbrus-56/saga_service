from datetime import datetime
from enum import Enum
from typing import Literal
import uuid
from fastapi import Depends, FastAPI
from faststream.rabbit.fastapi import RabbitRouter, RabbitBroker
from faststream.rabbit import RabbitQueue, RabbitExchange, ExchangeType


from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pydantic import BaseModel, Field, model_validator


router = RabbitRouter("amqp://admin:secret@localhost:5672/")

client: AsyncIOMotorClient = AsyncIOMotorClient(
    "mongodb://root:secret@127.0.0.1:27018/ecom?authSource=admin"
)


async def get_db() -> AsyncIOMotorDatabase:
    return client.get_database()


class OrderStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class OrderItem(BaseModel):
    product_id: uuid.UUID = Field(
        examples=["550e8400-e29b-41d4-a716-446655440000"],
        description="Уникальный идентификатор товара",
    )
    quantity: int = Field(
        gt=0,
        examples=[2],
        description="Количество товара в заказе",
    )
    price: float = Field(
        examples=[99.99],
        description="Цена за единицу на момент заказа",
    )


class Order(BaseModel):
    order_id: uuid.UUID
    user_id: uuid.UUID
    items: list[OrderItem]
    status: OrderStatus
    created_at: int
    updated_at: int = Field(
        default_factory=lambda: int(datetime.now().timestamp() * 1e3)
    )

    @model_validator(mode="after")
    def convert_uuid_to_str(self) -> "Order":
        self.order_id = str(self.order_id)
        self.user_id = str(self.user_id)
        for item in self.items:
            item.product_id = str(item.product_id)
        return self


class StatusSaga(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class SagaState(BaseModel):
    correlation_id: str
    order_id: str
    status: StatusSaga
    steps: list[str]


queue = RabbitQueue(name="saga_command", routing_key="saga.start", durable=True)
exchange = RabbitExchange("orders", type=ExchangeType.TOPIC, durable=True)


async def update_saga_state(
    storage: AsyncIOMotorDatabase,
    order_id: str,
    status: str,
    step: str,
):
    await storage.sagas.update_one(
        {"order_id": order_id},
        {
            "$set": {"status": status},
            "$push": {"steps": step},
        },
        upsert=True,
    )


@router.subscriber(queue, exchange)
async def saga_commands(
    msg: Order,
    broker: RabbitBroker,
    storage: AsyncIOMotorDatabase = Depends(get_db),
):
    order_id = str(msg.order_id)

    # Сохраняем начальное состояние саги
    await storage.sagas.insert_one(
        {
            "order_id": order_id,
            "status": StatusSaga.PENDING,
            "steps": [],
            "compensation_data": msg.model_dump(),
        }
    )

    try:
        # 1. Проверка и резерв товара
        reserve_ok = await broker.publish(
            msg,
            exchange="orders",
            routing_key="order.inventory",
            rpc=True,  # Ждем ответа
        )
        if not reserve_ok:
            raise Exception("Inventory reserve failed")
        await update_saga_state(
            storage,
            order_id,
            StatusSaga.COMPLETED,
            "inventory_reserved",
        )
        # # 2. Процессинг платежа
        # payment_result = await broker.publish(
        #     {
        #         "order_id": order_id,
        #         "user_id": msg["user_id"],
        #         "amount": 999.99,  # Расчет суммы
        #     },
        #     queue="process_payment",
        #     rpc=True,
        # )

        # # 3. Уведомление
        # await broker.publish(
        #     {
        #         "order_id": order_id,
        #         "user_id": msg["user_id"],
        #         "message": "Order completed",
        #     },
        #     queue="send_notification",
        # )

    except Exception as e:
        # Запуск компенсаций
        # await broker.publish({"order_id": order_id}, queue="cancel_order")
        print(f"Saga failed: {e}")


app = FastAPI()
app.include_router(router)
