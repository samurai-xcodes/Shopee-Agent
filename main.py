from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field


class TaskCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    prompt: str = Field(min_length=1)


class Task(BaseModel):
    task_id: UUID
    prompt: str
    status: Literal["PENDING"] = "PENDING"


app = FastAPI()
tasks: dict[UUID, Task] = {}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/tasks", status_code=201, response_model=Task)
def create_task(body: TaskCreate):
    task = Task(task_id=uuid4(), prompt=body.prompt)
    tasks[task.task_id] = task
    return task


@app.get("/tasks/{task_id}", response_model=Task)
def get_task(task_id: UUID):
    task = tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
