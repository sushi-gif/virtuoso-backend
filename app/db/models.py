from sqlalchemy import (
    create_engine, MetaData, Table, Column, Integer, String,
    Boolean, DateTime, Text, ForeignKey
)
from datetime import datetime
from app.core.security import hash_password
from app.db.database import database
from app.core.variables import DEFAULT_ADMIN, DEFAULT_ADMIN_PWD
DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String, unique=True, index=True),
    Column("email", String, unique=True, index=True),
    Column("hashed_password", String),
    Column("is_active", Boolean, default=True),
    Column("is_admin", Boolean, default=False),
    Column("created_at", DateTime, default=datetime.utcnow),
    Column("updated_at", DateTime, default=datetime.utcnow, onupdate=datetime.utcnow),
)

templates = Table(
    "templates",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String, unique=True, nullable=False),
    Column("namespace", String, nullable=False, default="default"),
    Column("max_cpu", Integer, nullable=False),
    Column("max_space", Integer, nullable=False),
    Column("max_ram", Integer, nullable=False),
    Column("qemu_image", String, nullable=False),
    Column("description", String, nullable=True),
    Column("created_by", Integer, ForeignKey("users.id")),
    Column("created_at", DateTime, default=datetime.utcnow),
)

vm_instances = Table(
    "vm_instances",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String, unique=True, nullable=False),  # Kubernetes VM name
    Column("namespace", String, nullable=False),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("template_id", Integer, ForeignKey("templates.id"), nullable=True),
    Column("created_at", DateTime, default=datetime.utcnow),
)

vm_costs = Table(
    "vm_cost",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("vm_instance_id", Integer, ForeignKey("vm_instances.id"), nullable=False),
    Column("cpu_cores", Integer, nullable=False),
    Column("ram_gb", Integer, nullable=False),
    Column("cost_per_hour", Integer, nullable=False),  # Store in cents/millicents
    Column("recorded_at", DateTime, default=datetime.utcnow),
)

vm_snapshots = Table(
    "vm_snapshots",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("vm_instance_id", Integer, ForeignKey("vm_instances.id"), nullable=False),
    Column("snapshot_name", String, unique=True, nullable=False),
    Column("created_at", DateTime, default=datetime.utcnow),
)


def create_tables():
    """Create all tables in the database."""
    print(datetime.utcnow())
    metadata.create_all(engine)


async def init_admin():
    query = users.select().where(users.c.username == "admin")
    admin_user = await database.fetch_one(query)
    
    if not admin_user:
        query = users.insert().values(
            username=DEFAULT_ADMIN, email="", hashed_password=hash_password(DEFAULT_ADMIN_PWD), is_admin=True
        )
        await database.execute(query)
