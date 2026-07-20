"""Todos router."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Todo, TodoStatus, Priority, TodoSource, EntityType
from app.auth import get_current_owner

router = APIRouter(prefix="/todos", tags=["todos"])


class TodoCreate(BaseModel):
    title: str
    due_date: str | None = None
    priority: str = "medium"
    source: str = "manual"
    assigned_to_user_id: int | None = None
    linked_entity_type: str | None = None
    linked_entity_id: int | None = None


class TodoUpdate(BaseModel):
    title: str | None = None
    due_date: str | None = None
    priority: str | None = None
    status: str | None = None
    assigned_to_user_id: int | None = None


@router.get("")
def list_todos(
    status: str = Query(default=""),
    priority: str = Query(default=""),
    source: str = Query(default=""),
    entity_type: str = Query(default=""),
    entity_id: int = Query(default=0),
    assigned_to_user_id: int = Query(default=0),
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    q = db.query(Todo).filter(Todo.owner_id == owner_id)

    if status:
        q = q.filter(Todo.status == status)
    if priority:
        q = q.filter(Todo.priority == priority)
    if source:
        q = q.filter(Todo.source == source)
    if entity_type and entity_id:
        q = q.filter(Todo.linked_entity_type == entity_type, Todo.linked_entity_id == entity_id)

    if assigned_to_user_id:
        q = q.filter(Todo.assigned_to_user_id == assigned_to_user_id)

    todos = q.order_by(Todo.due_date.asc().nullslast(), Todo.created_at.desc()).all()
    return [t.to_dict() for t in todos]


@router.post("")
def create_todo(
    data: TodoCreate,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    due_date = None
    if data.due_date:
        try:
            due_date = datetime.fromisoformat(data.due_date)
        except (ValueError, TypeError):
            pass

    valid_priorities = {e.value for e in Priority}
    valid_sources = {e.value for e in TodoSource}
    valid_entity_types = {e.value for e in EntityType}

    todo = Todo(
        title=data.title,
        due_date=due_date,
        priority=data.priority if data.priority in valid_priorities else Priority.medium.value,
        status=TodoStatus.open.value,
        source=data.source if data.source in valid_sources else TodoSource.manual.value,
        assigned_to_user_id=data.assigned_to_user_id,
        linked_entity_type=data.linked_entity_type if data.linked_entity_type in valid_entity_types else None,
        linked_entity_id=data.linked_entity_id,
        owner_id=owner_id,
    )
    db.add(todo)
    db.commit()
    db.refresh(todo)
    return todo.to_dict()


@router.put("/{todo_id}")
def update_todo(
    todo_id: int,
    data: TodoUpdate,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    todo = _get_todo_or_404(todo_id, owner_id, db)

    if data.title is not None:
        todo.title = data.title
    if data.due_date is not None:
        if data.due_date == "":
            todo.due_date = None   # explicit clear
        else:
            try:
                todo.due_date = datetime.fromisoformat(data.due_date)
            except (ValueError, TypeError):
                pass
    if data.priority is not None and data.priority in {e.value for e in Priority}:
        todo.priority = data.priority
    if data.status is not None and data.status in {e.value for e in TodoStatus}:
        todo.status = data.status
    if data.assigned_to_user_id is not None:
        todo.assigned_to_user_id = data.assigned_to_user_id if data.assigned_to_user_id > 0 else None

    db.commit()
    db.refresh(todo)
    return todo.to_dict()


@router.delete("/{todo_id}")
def delete_todo(
    todo_id: int,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    todo = _get_todo_or_404(todo_id, owner_id, db)
    db.delete(todo)
    db.commit()
    return {"ok": True}


def _get_todo_or_404(todo_id: int, owner_id: int, db: Session) -> Todo:
    todo = db.query(Todo).filter(
        Todo.id == todo_id, Todo.owner_id == owner_id
    ).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo
