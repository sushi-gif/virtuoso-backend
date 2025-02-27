from fastapi import FastAPI, Request
from app.db.database import database
from app.db.models import create_tables, init_admin
from app.auth.routes import router as auth_router
from app.vms.routes import router as vms_router
from app.claude.routes import router as claude_router
from fastapi.middleware.cors import CORSMiddleware
from app.templates.routes import router as template_router
from app.core.variables import *

app = FastAPI(
    title="VM Manager",
    description="A web application to manage VMs on Kubernetes using KubeVirt",
    version="1.0.0",
)

origins = [
    FRONTEND_URL,
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Allow these origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)


# Include routers
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(vms_router, prefix="/vms", tags=["Virtual Machines"])
app.include_router(claude_router, prefix="/claude", tags=["Claude"])
app.include_router(template_router, prefix="/templates", tags=["Templates"])

# Startup and shutdown events
@app.on_event("startup")
async def startup():
    create_tables()  # Create tables if they don't exist
    await database.connect()
    await init_admin()


@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

# Root endpoint
@app.get("/")
async def read_root(request: Request):
    client_host = request.client.host
    return {"apiVersions": "v1","remoteAddress":client_host,"docs":"/docs"}
