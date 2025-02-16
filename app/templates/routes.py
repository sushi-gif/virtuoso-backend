from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime
import json
from app.db.database import database
from app.db.models import templates, users
from app.core.security import verify_token
from typing import Optional, Dict, Any
from app.templates.schemas import *

router = APIRouter()

# ------------------ Helper: Fetch User from DB ------------------
async def get_user_from_token(decoded_token: dict):
    """Fetch user details from DB based on JWT token (sub=username)."""
    query = users.select().where(users.c.username == decoded_token["sub"])
    user = await database.fetch_one(query)

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return dict(user)  # Convert row to dictionary

# ------------------ CREATE A VM TEMPLATE (Admins Only) ------------------
@router.post("/", response_model=TemplateResponse)
async def create_vm_template(template: TemplateCreate, token=Depends(verify_token)):
    """Create a new VM template. Only admins can create."""
    user = await get_user_from_token(token)
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Only admins can create VM templates")

    query = templates.insert().values(
        name=template.name,
        namespace=template.namespace,
        description=template.description,
        max_cpu=template.max_cpu,
        max_ram=template.max_ram,
        max_space=template.max_space,
        qemu_image=template.qemu_image,
        created_by=user["id"],  # Use user ID from DB
        created_at=datetime.utcnow()
    )
    template_id = await database.execute(query)

    return {
        **template.dict(),
        "id": template_id,
        "created_by": user["id"],
        "created_at": datetime.utcnow()
    }

# ------------------ LIST ALL VM TEMPLATES ------------------
@router.get("/", response_model=list[TemplateResponse])
async def list_templates():
    """List all VM templates. Everyone can see them."""
    query = templates.select()
    result = await database.fetch_all(query)

    return [
        {
            **dict(row)
        }
        for row in result
    ]

# ------------------ GET A SINGLE VM TEMPLATE ------------------
@router.get("/{template_id}", response_model=TemplateResponse)
async def get_vm_template(template_id: int):
    """Get details of a VM template by ID. Everyone can view."""
    query = templates.select().where(templates.c.id == template_id)
    result = await database.fetch_one(query)

    if not result:
        raise HTTPException(status_code=404, detail="VM Template not found")

    return {
        **dict(result)
    }

# ------------------ UPDATE A VM TEMPLATE (Admins Only) ------------------
@router.put("/{template_id}", response_model=TemplateResponse)
async def update_vm_template(template_id: int, template: TemplateCreate, token=Depends(verify_token)):
    """Update a VM template. Only admins can update."""
    user = await get_user_from_token(token)
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Only admins can update VM templates")

    query = templates.select().where(templates.c.id == template_id)
    existing_template = await database.fetch_one(query)

    if not existing_template:
        raise HTTPException(status_code=404, detail="VM Template not found")

    query = (
        templates.update()
        .where(templates.c.id == template_id)
        .values(
            name=template.name,
            namespace=template.namespace,
            description=template.description,
            max_cpu=template.max_cpu,
            max_ram=template.max_ram,
            max_space=template.max_space,
            qemu_image=template.qemu_image,
        )
    )
    await database.execute(query)

    return {
        **template.dict(),
        "id": template_id,
        "created_by": existing_template["created_by"],
        "created_at": existing_template["created_at"]
    }

# ------------------ DELETE A VM TEMPLATE (Admins Only) ------------------
@router.delete("/{template_id}")
async def delete_vm_template(template_id: int, token=Depends(verify_token)):
    """Delete a VM template. Only admins can delete."""
    user = await get_user_from_token(token)
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Only admins can delete VM templates")

    query = templates.select().where(templates.c.id == template_id)
    existing_template = await database.fetch_one(query)

    if not existing_template:
        raise HTTPException(status_code=404, detail="VM Template not found")

    query = templates.delete().where(templates.c.id == template_id)
    await database.execute(query)

    return {"message": "VM Template deleted successfully"}
