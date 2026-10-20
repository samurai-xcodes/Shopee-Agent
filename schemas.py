from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TaskCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    prompt: str = Field(min_length=1, max_length=4000)


class TaskView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    task_id: UUID
    prompt: str
    status: Literal['PENDING', 'RUNNING', 'WAITING_APPROVAL', 'SUCCESS', 'FAILED']
    created_at: float
    updated_at: float
    attempts: int
    error: str | None
    result: dict | None
    approved_version: UUID | None
    trace_id: str
    provider: str


class Brief(BaseModel):
    product: str = Field(min_length=1, max_length=120)
    selling_points: list[str] = Field(min_length=1, max_length=5)
    style: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=100)
    price: str = Field(max_length=40)


class Document(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=100)
    price: str = Field(max_length=40)
    style: str = Field(max_length=120)
    image_ref: str = Field(pattern=r'^[a-f0-9]{64}\.png$')
    simulated: bool


class EditRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    title: str | None = Field(default=None, min_length=1, max_length=100)
    price: str | None = Field(default=None, max_length=40)


class Approval(BaseModel):
    version_id: UUID


class RetryRequest(BaseModel):
    acknowledge_possible_duplicate_charge: bool = False


class VersionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    version_id: UUID
    task_id: UUID
    number: int
    parent_id: UUID | None
    document: Document
    created_at: float
