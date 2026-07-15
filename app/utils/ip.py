"""客户端 IP 提取工具"""
from fastapi import Request


def get_client_ip(request: Request) -> str:
    """获取客户端真实 IP（优先从代理头获取）"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
