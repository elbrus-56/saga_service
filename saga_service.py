import uuid
from datetime import datetime
from enum import Enum

from fastapi import Depends, FastAPI
from faststream.rabbit import ExchangeType, RabbitExchange, RabbitQueue
from faststream.rabbit.fastapi import RabbitBroker, RabbitRouter
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pydantic import BaseModel, Field, field_validator

from configs import settings

router = RabbitRouter(settings.rabbit_uri)
client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongo_uri)


async def get_db() -> AsyncIOMotorDatabase:
    return client.get_database()


class OrderStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class OrderItem(BaseModel):
    product_id: str = Field(  # Изменено на str для хранения UUID в виде строки
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
    order_id: str  # Изменено на str
    user_id: str  # Изменено на str
    items: list[OrderItem]
    status: OrderStatus
    created_at: int = Field(
        default_factory=lambda: int(
            datetime.now().timestamp() * 1000
        )  # Явное приведение к int
    )
    updated_at: int = Field(
        default_factory=lambda: int(datetime.now().timestamp() * 1000)
    )

    @field_validator("order_id", "user_id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, value: uuid.UUID | str) -> str:
        if isinstance(value, uuid.UUID):
            return str(value)
        return value


class StatusSaga(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class SagaState(BaseModel):
    correlation_id: str
    order_id: str
    status: StatusSaga
    steps: list[str]


exchange = RabbitExchange("orders", type=ExchangeType.TOPIC, durable=True)


async def update_saga_state(
    storage: AsyncIOMotorDatabase,
    order_id: str,
    status: StatusSaga,  # Используем Enum
    step: str,
):
    await storage.sagas.update_one(
        {"order_id": order_id},
        {
            "$set": {"status": status.value},  # Сохраняем значение Enum
            "$push": {"steps": step},
        },
        upsert=True,
    )


@router.subscriber(
    RabbitQueue(
        name="saga_start_queue",
        routing_key="saga.start",
    ),
    exchange,
)
async def saga_command_start(
    msg: Order,
    broker: RabbitBroker,
    storage: AsyncIOMotorDatabase = Depends(get_db),
):
    try:
        order_id = msg.order_id
        await update_saga_state(
            storage,
            order_id,
            StatusSaga.PENDING,
            "inventory_reserved",
        )
        await broker.publish(
            msg,
            exchange="orders",
            routing_key="order.inventory",
        )
    except Exception as e:
        await broker.publish(
            {"error": str(e), "order": msg.model_dump()},
            exchange="orders",
            routing_key="saga.errors",
        )


@router.subscriber(
    RabbitQueue(
        name="saga_inventory_queue",
        routing_key="saga.inventory.reserved",
    ),
    exchange,
)
async def saga_inventory_reserv_command(
    msg: Order,
    broker: RabbitBroker,
    storage: AsyncIOMotorDatabase = Depends(get_db),
):
    try:
        order_id = msg.order_id
        await update_saga_state(
            storage,
            order_id,
            StatusSaga.PENDING,
            "payment",
        )
        await broker.publish(
            msg,
            exchange="orders",
            routing_key="order.payment",
        )
    except Exception as e:
        await broker.publish(
            {"error": str(e), "order": msg.model_dump()},
            exchange="orders",
            routing_key="saga.errors",
        )


@router.subscriber(
    RabbitQueue(
        name="saga_notify_queue",
        routing_key="saga.notify",
    ),
    exchange,
)
async def saga_notify_command(
    msg: Order,
    broker: RabbitBroker,
    storage: AsyncIOMotorDatabase = Depends(get_db),
):
    try:
        order_id = msg.order_id
        await update_saga_state(
            storage,
            order_id,
            StatusSaga.COMPLETED,
            "notified",
        )
        await broker.publish(
            msg,
            exchange="orders",
            routing_key="order.notify.success",  # Отдельный ключ для успеха
        )
    except Exception as e:
        await broker.publish(
            {"error": str(e), "order": msg.model_dump()},
            exchange="orders",
            routing_key="saga.errors",
        )


@router.subscriber(
    RabbitQueue(
        name="saga_compensation_queue",
        routing_key="saga.compensation",
    ),
    exchange,
)
async def saga_compensation(
    msg: Order,
    broker: RabbitBroker,
    storage: AsyncIOMotorDatabase = Depends(get_db),
):
    try:
        order_id = msg.order_id
        saga = await storage.sagas.find_one({"order_id": order_id})

        if not saga:
            raise ValueError(f"Saga for order {order_id} not found")

        if "payment_processed" in saga.get("steps", []):
            await broker.publish(
                msg,
                exchange="orders",
                routing_key="order.inventory.compensation",
            )
        if "inventory_reserved" in saga.get("steps", []):
            await broker.publish(
                msg,
                exchange="orders",
                routing_key="order.compensations",
            )

        await update_saga_state(
            storage,
            order_id,
            StatusSaga.FAILED,
            "compensated",
        )
        await broker.publish(
            msg,
            exchange="orders",
            routing_key="order.notify.failure",
        )
    except Exception as e:
        await broker.publish(
            {"error": str(e), "order": msg.model_dump()},
            exchange="orders",
            routing_key="saga.errors",
        )


app = FastAPI()
app.include_router(router)
