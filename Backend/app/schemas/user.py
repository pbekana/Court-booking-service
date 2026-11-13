from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserRegister(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)

    model_config = ConfigDict(extra="forbid")

    @field_validator("password")
    @classmethod
    def password_must_fit_bcrypt(cls, password: str) -> str:
        if len(password.encode("utf-8")) > 72:
            raise ValueError("Password must not exceed 72 UTF-8 bytes")
        return password


class UserResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    role: str

    model_config = ConfigDict(from_attributes=True)
