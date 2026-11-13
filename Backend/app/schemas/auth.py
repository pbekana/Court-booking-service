from typing import Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserPublic(BaseModel):
    id: Union[UUID, int, str]
    full_name: str
    email: EmailStr
    role: str

    model_config = ConfigDict(from_attributes=True)


class AuthResponse(BaseModel):
    user: UserPublic
    token: str
