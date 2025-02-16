from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime

class TemplateBase(BaseModel):
    name: str
    namespace: str = "default"
    description: Optional[str] = None
    max_cpu: int
    max_ram: int
    max_space: int
    qemu_image: str

class TemplateCreate(TemplateBase):
    pass

class TemplateResponse(TemplateBase):
    id: int
    created_at: datetime
    created_by: int

    class Config:
        from_attributes = True