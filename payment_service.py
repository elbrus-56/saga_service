import random
import uuid
from enum import Enum

from fastapi import Depends, FastAPI
from faststream.rabbit import ExchangeType, RabbitExchange, RabbitQueue
from faststream.rabbit.fastapi import RabbitRouter
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pydantic import BaseModel, model_validator

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
    product_id: uuid.UUID
    quantity: int
    price: float


class Order(BaseModel):
    order_id: uuid.UUID
    user_id: uuid.UUID
    items: list[OrderItem]
    status: OrderStatus
    created_at: int
    updated_at: int

    @model_validator(mode="after")
    def convert_uuid_to_str(self) -> "Order":
        self.order_id = str(self.order_id)
        self.user_id = str(self.user_id)
        for item in self.items:
            item.product_id = str(item.product_id)
        return self


exchange = RabbitExchange("orders", type=ExchangeType.TOPIC, durable=True)


@router.subscriber(RabbitQueue(name="", routing_key="order.payment"), exchange)
async def payment_service(
    order: Order,
    storage: AsyncIOMotorDatabase = Depends(get_db),
):
    choice = random.choice([True, False])
    if not choice:
        await router.broker.publish(
            order,
            exchange="orders",
            routing_key="saga.compensation",
        )
        raise Exception("Оплата не удалась")
    await router.broker.publish(
        order,
        exchange="orders",
        routing_key="saga.notify",
    )
    return True


app = FastAPI()
app.include_router(router)
