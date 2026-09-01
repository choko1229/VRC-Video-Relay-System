from datetime import datetime

from pydantic import BaseModel

from app.models.user import UserRole, UserStatus


class UserOut(BaseModel):
    id: int
    username: str
    discord_id: str | None
    status: UserStatus
    role: UserRole
    applied_at: datetime
    approved_at: datetime | None

    model_config = {"from_attributes": True}
