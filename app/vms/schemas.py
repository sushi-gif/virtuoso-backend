from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class CreateVM(BaseModel):
    name: str
    template_id: int
    cpu: int
    ram: int
    space: int
    password: str

# ------------------ VM Instance Metadata (From DB) ------------------
class VmInstanceBase(BaseModel):
    id: int
    name: str
    namespace: str
    user_id: int
    template_id: int  
    created_at: datetime

# ------------------ Kubernetes Data (If VM Exists) ------------------
class Disk(BaseModel):
    name: str
    bus: Optional[str] = None

class Network(BaseModel):
    name: str

class Volume(BaseModel):
    name: str
    containerDiskImage: Optional[str] = None

class PersistentVolumeClaim(BaseModel):
    name: str
    size: Optional[str] = None
    status: Optional[str] = None

class KubernetesVmStatus(BaseModel):
    uid: Optional[str]
    creationTimestamp: Optional[str]
    cores: Optional[int]
    memory: Optional[str] = "Unknown"
    status: Optional[str] = "Not Found"
    networks: List[Network] = []
    disks: List[Disk] = []
    volumes: List[Volume] = []
    pvcs: List[PersistentVolumeClaim] = []  # ✅ Added PVCs

# ------------------ FULL VM RESPONSE (DB + Kubernetes) ------------------
class VirtualMachineResponse(VmInstanceBase):
    kube_status: KubernetesVmStatus

# Request model for creating a snapshot
class CreateVMSnapshotRequest(BaseModel):
    namespace: str

class VMSnapshot(BaseModel):
    id: int
    name: str
    namespace: str
    creationTimestamp: Optional[str] = None

class PatchVM(BaseModel):
    cpu: Optional[int] = None
    ram: Optional[int] = None
