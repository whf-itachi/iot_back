"""JetLinks API 客户端 — 对接 JetLinks IoT 平台"""
import httpx
from ..config import settings


class JetLinksClient:
    """JetLinks IoT 平台 API 客户端"""

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

    async def _get(self, path: str) -> dict:
        await self._ensure_token()
        async with httpx.AsyncClient(verify=False, timeout=30) as client:
            headers = {
                "Content-Type": "application/json",
                "X-Access-Token": self._token or "",
            }
            resp = await client.get(f"{self.base}{path}", headers=headers)
            if resp.status_code == 401:
                await self.login()
                headers["X-Access-Token"] = self._token or ""
                resp = await client.get(f"{self.base}{path}", headers=headers)
            return resp.json()

    # ==================== 聚合接口 ====================

    async def get_device_summary(self) -> dict:
        """设备摘要 KPI"""
        result = await self._post("/device/instance/_query", {"pageSize": 200})
        devices = result.get("result", {}).get("data", [])
        total = len(devices)
        online = sum(1 for d in devices if d.get("state", {}).get("value") == "online")
        return {"total": total, "online": online, "offline": total - online}

    async def get_device_status(self) -> list[dict]:
        """设备状态分布"""
        result = await self._post("/device/instance/_query", {"pageSize": 200})
        devices = result.get("result", {}).get("data", [])
        status_count: dict[str, int] = {}
        for d in devices:
            st = d.get("state", {}).get("text", "未知")
            status_count[st] = status_count.get(st, 0) + 1
        return [{"name": k, "value": v} for k, v in status_count.items()]

    async def get_spindle_trend(self) -> list[dict]:
        """主轴转速趋势"""
        result = await self._post(
            f"/device/product/{self.product_id}/properties/_query",
            {"pageSize": 500, "orderBy": "timestamp desc"},
        )
        props = result.get("result", {}).get("data", [])
        device_speeds: dict[str, list[float]] = {}
        for p in props:
            did = p.get("deviceId", "?")
            speed = p.get("spingle_speed", 0) or 0
            device_speeds.setdefault(did, []).append(speed)

        items = []
        for did, speeds in list(device_speeds.items())[:10]:
            avg = round(sum(speeds) / len(speeds), 1)
            items.append({"name": did[-6:], "value": avg})
        return items

    async def get_feedrate(self) -> list[dict]:
        """进给率"""
        result = await self._post(
            f"/device/product/{self.product_id}/properties/_query",
            {"pageSize": 500, "orderBy": "timestamp desc"},
        )
        props = result.get("result", {}).get("data", [])
        device_rates: dict[str, list[float]] = {}
        for p in props:
            did = p.get("deviceId", "?")
            rate = p.get("feed_rate", 0) or 0
            device_rates.setdefault(did, []).append(rate)

        items = []
        for did, rates in list(device_rates.items())[:10]:
            avg = round(sum(rates) / len(rates), 1)
            items.append({"name": did[-6:], "value": avg})
        return items

    async def query_process_logs(self, blade_id: str) -> dict:
        """查询叶片加工日志"""
        if not blade_id:
            return {"success": False, "message": "请输入叶片编号", "results": [], "total": 0}

        devices_result = await self._post("/device/instance/_query", {"pageSize": 200})
        devices = devices_result.get("result", {}).get("data", [])

        all_logs = []
        for device in devices:
            did = device.get("id")
            if not did:
                continue
            try:
                log_path = (
                    f"/device/instance/{did}/logs"
                    "?pageSize=100&orderBy=timestamp%20desc"
                    "&terms%5B0%5D.column=type&terms%5B0%5D.value=event"
                )
                logs_result = await self._get(log_path)
                logs = logs_result.get("result", {}).get("data", []) or []

                for entry in logs:
                    content = entry.get("content", {}) or {}
                    if isinstance(content, str):
                        try:
                            import json
                            content = json.loads(content)
                        except (json.JSONDecodeError, TypeError):
                            pass

                    if not isinstance(content, dict):
                        continue
                    if content.get("event") != "process_log_report":
                        continue

                    event_data = content.get("data", {}) or {}
                    log_blade_id = str(event_data.get("blade_id", "")).strip()
                    if log_blade_id and blade_id.lower() in log_blade_id.lower():
                        event_data["_deviceId"] = did
                        event_data["_deviceName"] = device.get("name", "")
                        event_data["_timestamp"] = entry.get("timestamp", "")
                        event_data["_logId"] = content.get("messageId", "")
                        all_logs.append(event_data)
            except Exception:
                continue

        all_logs.sort(key=lambda x: x.get("_timestamp", 0) or 0, reverse=True)
        return {
            "success": True,
            "message": f"找到 {len(all_logs)} 条加工日志",
            "results": all_logs,
            "data": all_logs,
            "total": len(all_logs),
        }

    async def query_flatness(self, blade_id: str | None = None) -> dict:
        """查询平面度测量数据"""
        devices_result = await self._post("/device/instance/_query", {"pageSize": 200})
        devices = devices_result.get("result", {}).get("data", [])

        all_logs = []
        for device in devices:
            did = device.get("id")
            if not did:
                continue
            try:
                log_path = (
                    f"/device/instance/{did}/logs"
                    "?pageSize=100&orderBy=timestamp%20desc"
                    "&terms%5B0%5D.column=type&terms%5B0%5D.value=event"
                )
                logs_result = await self._get(log_path)
                logs = logs_result.get("result", {}).get("data", []) or []

                for entry in logs:
                    content = entry.get("content", {}) or {}
                    if isinstance(content, str):
                        try:
                            import json
                            content = json.loads(content)
                        except (json.JSONDecodeError, TypeError):
                            pass

                    if not isinstance(content, dict):
                        continue
                    if content.get("event") != "flatness_data":
                        continue

                    event_data = content.get("data", {}) or {}
                    if blade_id:
                        log_blade_id = str(event_data.get("blade_id", "")).strip()
                        if log_blade_id and blade_id.lower() not in log_blade_id.lower():
                            continue

                    event_data["_deviceId"] = did
                    event_data["_deviceName"] = device.get("name", "")
                    event_data["_timestamp"] = entry.get("timestamp", "")
                    event_data["_logId"] = content.get("messageId", "")
                    all_logs.append(event_data)
            except Exception:
                continue

        all_logs.sort(key=lambda x: x.get("_timestamp", 0) or 0, reverse=True)
        return {
            "success": True,
            "message": f"找到 {len(all_logs)} 条平面度测量数据",
            "results": all_logs,
            "data": all_logs,
            "total": len(all_logs),
        }

    async def get_device_list(self, page: int = 1, page_size: int = 50,
                              status: str | None = None,
                              keyword: str | None = None) -> dict:
        """设备列表（分页）"""
        body: dict = {"pageSize": page_size}
        if page > 0:
            body["pageIndex"] = page
        if status:
            body["where"] = f"state.value = '{status}'"
        if keyword:
            body["where"] = f"name like '%{keyword}%'"

        result = await self._post("/device/instance/_query", body)
        pager = result.get("result", {})
        return {
            "data": pager.get("data", []),
            "total": pager.get("total", 0),
            "page": pager.get("pageIndex", 1),
            "pageSize": pager.get("pageSize", 50),
        }

    async def get_device_detail(self, device_id: str) -> dict:
        """设备详情：基本信息 + 物模型 + 最近属性"""
        import json

        dev_result = await self._get(f"/device/instance/{device_id}")
        dev = dev_result.get("result", {})

        product_result = await self._get(f"/device/product/{self.product_id}")
        product = product_result.get("result", {})
        metadata = product.get("metadata", {})
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}

        properties = []
        events = []
        if isinstance(metadata, dict):
            for prop in metadata.get("properties", []):
                properties.append({
                    "id": prop.get("id"),
                    "name": prop.get("name"),
                    "type": (prop.get("valueType") or {}).get("type", "string"),
                })
            for evt in metadata.get("events", []):
                events.append({
                    "id": evt.get("id"),
                    "name": evt.get("name"),
                    "level": (evt.get("expands") or {}).get("level", "ordinary"),
                })

        recent = []
        prop_total = 0
        try:
            props_result = await self._post(
                f"/device/product/{self.product_id}/properties/_query",
                {
                    "pageSize": 20,
                    "orderBy": "timestamp desc",
                    "terms": [{"column": "deviceId", "termType": "eq", "value": device_id}],
                },
            )
            prop_data = props_result.get("result", {}).get("data", []) or []
            prop_total = props_result.get("result", {}).get("total", 0)
            for p in prop_data:
                recent.append({
                    "timestamp": p.get("timestamp"),
                    "run_status": p.get("run_status"),
                    "spindle_speed": p.get("spingle_speed"),
                    "feed_rate": p.get("feed_rate"),
                    "blade_model": p.get("blade_model"),
                    "task_id": p.get("task_id"),
                })
        except Exception:
            pass

        return {
            "device": {
                "id": device_id,
                "name": dev.get("name", ""),
                "productName": product.get("name", ""),
                "state": (dev.get("state") or {}).get("text", "未知"),
            },
            "properties": properties,
            "events": events,
            "recentProperties": recent,
            "propertyTotal": prop_total,
        }

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
