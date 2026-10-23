import uuid

from pydantic import BaseModel, ConfigDict, Field


class RoomRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    member_limit: int
    is_public: bool
    host_id: uuid.UUID | None


class PublicRoomRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    member_limit: int
    member_count: int


class RoomCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_public: bool = True
    member_limit: int = Field(default=5, ge=2, le=50)


class RoomHandover(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
