import uuid
from datetime import datetime
from enum import Enum

from fastapi import Depends, FastAPI
from faststream.rabbit.fastapi import RabbitRouter
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pydantic import BaseModel, Field, model_validator
from faststream.rabbit import ExchangeType, RabbitExchange, RabbitQueue

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
    order_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        examples=["123e4567-e89b-12d3-a456-426614174000"],
        description="Уникальный идентификатор заказа",
    )
    user_id: uuid.UUID = Field(
        examples=["550e8400-e29b-41d4-a716-446655440000"],
        description="Идентификатор пользователя",
    )
    items: list[OrderItem] = Field(
        min_length=1,
        examples=[
            [
                {
                    "product_id": "550e8400-e29b-41d4-a716-446655440000",
                    "quantity": 2,
                    "price": 99.99,
                },
            ]
        ],
        description="Список товаров в заказе",
    )
    status: OrderStatus = Field(
        default=OrderStatus.PENDING,
        examples=["pending"],
        description="Текущий статус заказа",
    )
    created_at: int = Field(
        default_factory=lambda: int(datetime.now().timestamp() * 1e3),
        description="Дата создания заказа",
        examples=[1748844512281],
    )
    updated_at: int = Field(
        default_factory=lambda: int(datetime.now().timestamp() * 1e3),
        description="Дата обновления заказа",
        examples=[1748844512281],
    )

    @model_validator(mode="after")
    def convert_uuid_to_str(self) -> "Order":
        self.order_id = str(self.order_id)
        self.user_id = str(self.user_id)
        for item in self.items:
            item.product_id = str(item.product_id)
        return self


@router.post("/create_order")
async def create_order(
    order: Order,
    storage: AsyncIOMotorDatabase = Depends(get_db),
) -> Order:
    await storage.orders.insert_one(order.model_dump())
    await router.broker.publish(
        order,
        exchange="orders",
        routing_key="saga.start",
    )
    return order


exchange = RabbitExchange("orders", type=ExchangeType.TOPIC, durable=True)


@router.subscriber(
    RabbitQueue(
        name="",
        routing_key="order.compensations",
    ),
    exchange,
)
async def compensation_order(
    order: Order,
    storage: AsyncIOMotorDatabase = Depends(get_db),
):
    order.updated_at = int(datetime.now().timestamp() * 1e3)
    await storage.orders.update_one(
        {"order_id": str(order.order_id)},
        {
            "$set": {"status": OrderStatus.CANCELLED.value},
        },
    )


app = FastAPI()
app.include_router(router)
