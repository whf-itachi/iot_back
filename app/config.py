"""应用配置 — 所有敏感信息从 .env 文件读取，启动时校验必填项"""
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 数据库
    db_host: str = ""
    db_port: int = 3306
    db_user: str = ""
    db_password: str = ""
    db_name: str = ""

    # JWT
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24

    # JetLinks
    jetlinks_base_url: str = ""
    jetlinks_username: str = ""
    jetlinks_password: str = ""
    jetlinks_product_id: str = ""

    # Webhook（可选，允许为空）
    webhook_token: str = ""

    # 服务
    host: str = "0.0.0.0"
    port: int = 8080

    @model_validator(mode="after")
    def _validate_required(self):
        """启动时校验：必填字段为空则明确报错，指出缺少哪个 .env 变量"""
        required = {
            "db_host": "DB_HOST",
            "db_user": "DB_USER",
            "db_password": "DB_PASSWORD",
            "db_name": "DB_NAME",
            "jwt_secret": "JWT_SECRET",
            "jetlinks_base_url": "JETLINKS_BASE_URL",
            "jetlinks_username": "JETLINKS_USERNAME",
            "jetlinks_password": "JETLINKS_PASSWORD",
            "jetlinks_product_id": "JETLINKS_PRODUCT_ID",
        }
        missing = []
        for field, env_var in required.items():
            if not getattr(self, field):
                missing.append(f"  {env_var}  →  {field}")
        if missing:
            raise ValueError(
                "以下配置项为空，请检查 .env 文件是否存在且格式正确：\n"
                + "\n".join(missing)
                + "\n\n.env 文件应位于项目根目录（与 start.py 同级）"
            )
        return self

    @property
    def database_url(self) -> str:
        from urllib.parse import quote_plus
        return (
            f"mysql+aiomysql://{quote_plus(self.db_user)}:{quote_plus(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
            f"?charset=utf8mb4"
        )


settings = Settings()
