from datetime import datetime

from pydantic import BaseModel, Field

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


class RenameUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
