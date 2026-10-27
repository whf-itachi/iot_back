"""JetLinks API 客户端 — 对接 JetLinks IoT 平台。

说明：本项目的数据查询（叶片/加工日志/平面度/统计/告警/设备状态）均只查本地库，
数据由 JetLinks 通过 webhook 主动推送落库。本客户端仅保留「管理端手动同步」所需的出站调用
（拉取 JetLinks 设备/产品写回本地 iot_device 表）。原有的实时代理方法（device/summary、
device/status、device/list、device/{id}、spindle/trend、feedrate、query_process_logs、
query_flatness）已随架构收敛于 2026-10-21 移除，改由本地库查询替代。
"""
import httpx
from ..config import settings


class JetLinksClient:
    """JetLinks IoT 平台 API 客户端（仅用于主动同步）"""

    def __init__(self):
        self.base = settings.jetlinks_base_url
        self.username = settings.jetlinks_username
        self.password = settings.jetlinks_password
        self.product_id = settings.jetlinks_product_id
        self._token: str | None = None

    async def _ensure_token(self):
        if self._token:
            return
        await self.login()

    async def login(self):
        async with httpx.AsyncClient(verify=False) as client:
            resp = await client.post(
                f"{self.base}/authorize/login",
                json={"username": self.username, "password": self.password},
                timeout=10,
            )
            data = resp.json()
            self._token = data.get("result", {}).get("token", "")
            if not self._token:
                raise Exception("JetLinks 登录失败")

    async def _post(self, path: str, body: dict | None = None) -> dict:
        await self._ensure_token()
        async with httpx.AsyncClient(verify=False, timeout=30) as client:
            headers = {
                "Content-Type": "application/json",
                "X-Access-Token": self._token or "",
            }
            resp = await client.post(
                f"{self.base}{path}", json=body, headers=headers
            )
            if resp.status_code == 401:
                # Token 过期，重新登录后重试
                await self.login()
                headers["X-Access-Token"] = self._token or ""
                resp = await client.post(
                    f"{self.base}{path}", json=body, headers=headers
                )
            return resp.json()

    # ==================== 同步（管理端手动触发：拉取 JetLinks 设备/产品写回本地库） ====================

    async def sync_devices(self) -> list[dict]:
        """从 JetLinks 获取全部设备数据"""
        result = await self._post("/device/instance/_query", {"pageSize": 500})
        return result.get("result", {}).get("data", [])

    async def sync_products(self) -> list[dict]:
        """从 JetLinks 获取产品列表"""
        result = await self._post("/device/product/_query", {"pageSize": 200})
        return result.get("result", {}).get("data", [])


# 单例
jetlinks = JetLinksClient()
