from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mongo_uri: str = "mongodb://root:example@localhost:27017/ecom?authSource=admin"
    rabbit_uri: str = "amqp://admin:secret@localhost:5672/"


settings = Settings()
