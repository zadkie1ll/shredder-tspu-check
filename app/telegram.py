import httpx


async def send_message(settings, text: str) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        payload = {"chat_id": settings.telegram_chat_id, "text": text}
        if settings.telegram_message_thread_id is not None:
            payload["message_thread_id"] = settings.telegram_message_thread_id
        response = await client.post(url, json=payload)
        response.raise_for_status()
