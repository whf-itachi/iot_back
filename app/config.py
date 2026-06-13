"""应用配置"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 数据库
    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = "root"
    db_name: str = "iot"

    # JWT
    jwt_secret: str = "iot-dashboard-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24

    # JetLinks
    jetlinks_base_url: str = "http://haitch.tech:8848"
    jetlinks_username: str = "admin"
    jetlinks_password: str = "WHF123whf"
    jetlinks_product_id: str = "2061662500706525184"

    # Webhook
    webhook_token: str = ""

    # 服务
    host: str = "0.0.0.0"
    port: int = 8080

    @property
    def database_url(self) -> str:
        from urllib.parse import quote_plus
        return (
            f"mysql+aiomysql://{quote_plus(self.db_user)}:{quote_plus(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
            f"?charset=utf8mb4"
        )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
