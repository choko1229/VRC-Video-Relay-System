import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting

# WebUIから変更可能な運用設定のデフォルト値。
# .envは接続情報・秘密鍵のみとし、それ以外の運用パラメータはここ(DB)で管理する。
DEFAULTS: dict[str, Any] = {
    "connection_log_retention_days": 14,
    "local_log_retention_days": 14,
}


async def get(db: AsyncSession, key: str) -> Any:
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        return DEFAULTS.get(key)
    return json.loads(row.value)


async def set(db: AsyncSession, key: str, value: Any) -> None:
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    row = result.scalar_one_or_none()
    serialized = json.dumps(value)
    if row is None:
        db.add(AppSetting(key=key, value=serialized))
    else:
        row.value = serialized
    await db.flush()


async def get_all(db: AsyncSession) -> dict[str, Any]:
    result = await db.execute(select(AppSetting))
    stored = {row.key: json.loads(row.value) for row in result.scalars()}
    return {**DEFAULTS, **stored}
