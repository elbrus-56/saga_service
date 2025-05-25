from datetime import datetime
from enum import Enum
from typing import Literal
import uuid
from fastapi import Depends, FastAPI
from faststream.rabbit.fastapi import RabbitRouter
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


queue = RabbitQueue(name="inventory", routing_key="order.inventory", durable=True)
exchange = RabbitExchange("orders", type=ExchangeType.TOPIC, durable=True)


@router.subscriber(queue, exchange)
async def inventory_status(
    order: Order,
    storage: AsyncIOMotorDatabase = Depends(get_db),
):
    # Тупой способ сделать N-запросов в базу, но быстрый в реализации
    for item in order.items:
        product = await storage.products.find_one({"product_id": str(item.product_id)})
        if product["qty"] - item.quantity < 0:
            raise Exception("Товара нет в наличии")
        await storage.products.update_one(
            {"product_id": str(item.product_id)},
            {"$inc": {"qty": -item.quantity}},
        )
    return True


app = FastAPI()
app.include_router(router)
