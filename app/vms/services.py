import httpx
import json
from fastapi import HTTPException
from sqlalchemy import insert, select, delete
from app.db.database import database
from app.db.models import vm_instances, users, vm_costs
from app.vms.schemas import *
from app.core.variables import KUBERNETES_API_URL, HEADERS
from datetime import datetime
from typing import List, Optional
import uuid
import asyncio


min_abs = lambda a, b: ((b ^ ((a ^ b) & -(a < b))) ^ ((b ^ ((a ^ b) & -(a < b))) >> 31)) - ((b ^ ((a ^ b) & -(a < b))) >> 31)

# Fixed rates (cents per hour)
CPU_COST_PER_CORE = 10  # $0.10/core/hour
RAM_COST_PER_GB = 5     # $0.05/GB/hour
STORAGE_COST_PER_GB = 1 # $0.01/GB/hour

def calculate_cost(cpu: int, ram: int) -> int:
    return (cpu * CPU_COST_PER_CORE) + (ram * RAM_COST_PER_GB) 

# ------------------ HELPER: Check VM in Kubernetes ------------------
# ------------------ HELPER: Check VM in Kubernetes ------------------
# ------------------ HELPER: Check VM in Kubernetes ------------------
async def check_vm_in_kube(namespace: str, name: str) -> KubernetesVmStatus:
    """Check if a VM exists in Kubernetes and return its status, including attached PVCs."""
    url = f"{KUBERNETES_API_URL}/apis/kubevirt.io/v1/namespaces/{namespace}/virtualmachines/{name}"
    
    async with httpx.AsyncClient(verify=False) as client:
        response = await client.get(url, headers=HEADERS)

    if response.status_code != 200:
        return KubernetesVmStatus(
            uid=None,
            creationTimestamp=None,
            cores="Unknown",
            memory="Unknown",
            status="Not Found",
            networks=[],
            disks=[],
            volumes=[],
        )

    vm_data = response.json()
    metadata = vm_data.get("metadata", {})
    spec = vm_data.get("spec", {})
    status = vm_data.get("status", {})

    # Extract volumes and find PVCs
    volumes_data = spec.get("template", {}).get("spec", {}).get("volumes", [])
    volumes = []
    pvc_names = []
    
    for v in volumes_data:
        if "persistentVolumeClaim" in v:
            pvc_names.append(v["persistentVolumeClaim"]["claimName"])
        volumes.append(Volume(
            name=v.get("name"),
            containerDiskImage=v.get("containerDisk", {}).get("image")
        ))

    # Fetch details for each PVC
    pvcs = []
    async with httpx.AsyncClient(verify=False) as client:
        for pvc_name in pvc_names:
            pvc_url = f"{KUBERNETES_API_URL}/api/v1/namespaces/{namespace}/persistentvolumeclaims/{pvc_name}"
            pvc_response = await client.get(pvc_url, headers=HEADERS)
            
            if pvc_response.status_code == 200:
                pvc_data = pvc_response.json()
                pvcs.append(PersistentVolumeClaim(
                    name=pvc_name,
                    size=pvc_data.get("spec", {}).get("resources", {}).get("requests", {}).get("storage"),
                    status=pvc_data.get("status", {}).get("phase")
                ))
                

    return KubernetesVmStatus(
        uid=metadata.get("uid"),
        creationTimestamp=metadata.get("creationTimestamp"),
        cores=spec.get("template", {}).get("spec", {}).get("domain", {}).get("cpu", {}).get("cores", {}),
        memory=spec.get("template", {}).get("spec", {}).get("domain", {}).get("resources", {}).get("requests", {}).get("memory", "Unknown"),
        status=status.get("printableStatus", "Unknown"),
        networks=[Network(name=n.get("name")) for n in spec.get("template", {}).get("spec", {}).get("networks", [])],
        disks=[Disk(name=d.get("name"), bus=d.get("disk", {}).get("bus")) for d in spec.get("template", {}).get("spec", {}).get("domain", {}).get("devices", {}).get("disks", [])],
        volumes=volumes,
        pvcs=pvcs  # ✅ Now included in the response
    )

# ------------------ LIST ALL VMs ------------------
async def list_vms(user: dict) -> List[VirtualMachineResponse]:
    """List VM instances stored in the database and check their status in Kubernetes."""
    query = select(vm_instances)
    if not user["is_admin"]:
        query = query.where(vm_instances.c.user_id == user["id"])

    vms = await database.fetch_all(query)
    result = []

    for vm in vms:
        vm_dict = dict(vm)
        kube_status = await check_vm_in_kube(NAMESPACE, vm_dict["name"])
        result.append(VirtualMachineResponse(**vm_dict, kube_status=kube_status))

    return result


import asyncio
import httpx

async def wait_for_datavolume(namespace: str, dv_name: str, timeout: int = 300, interval: int = 5) -> bool:
    """
    Wait for a DataVolume to reach the 'Succeeded' phase in Kubernetes.
    
    Args:
        namespace (str): The namespace where the DataVolume is created.
        dv_name (str): The name of the DataVolume.
        timeout (int): Maximum time (seconds) to wait.
        interval (int): Time between checks (seconds).
    
    Returns:
        bool: True if DataVolume reaches 'Succeeded', False if timeout occurs.
    """
    url = f"{KUBERNETES_API_URL}/apis/cdi.kubevirt.io/v1beta1/namespaces/{namespace}/datavolumes/{dv_name}"

    start_time = asyncio.get_event_loop().time()
    
    while asyncio.get_event_loop().time() - start_time < timeout:
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(url, headers=HEADERS)

        if response.status_code == 200:
            dv_status = response.json().get("status", {})
            phase = dv_status.get("phase")

            if phase == "Succeeded":
                return True  # Success!

        await asyncio.sleep(interval)  # Wait before next check

    return False  # Timed out


# ------------------ MAIN FUNCTION: Create Virtual Machine ------------------
import uuid
import json
import httpx
from fastapi import HTTPException
from sqlalchemy import insert, select
from datetime import datetime
from app.db.database import database
from app.db.models import vm_instances, templates
from app.core.variables import KUBERNETES_API_URL, HEADERS, NAMESPACE

async def create_vm(payload, user):
    """Create a VM from a template after ensuring its DataVolume is ready."""
    # Fetch the template
    query = select(templates).where(templates.c.id == payload.template_id)
    template = await database.fetch_one(query)

    if not template:
        raise HTTPException(status_code=404, detail="VM Template not found")

    # Step 1️⃣: Generate a Unique DataVolume Name
    unique_dv_name = f"{payload.name}-dv-{uuid.uuid4().hex[:6]}"

    # todo replace max_space and max_cpu and max_ram with user input ram cpu etc.
    # Step 2️⃣: Create DataVolume first
    datavolume_body = {
        "apiVersion": "cdi.kubevirt.io/v1beta1",
        "kind": "DataVolume",
        "metadata": {"name": unique_dv_name, "namespace": NAMESPACE},
        "spec": {
            "source": {"http": {"url": template.qemu_image}},
            "pvc": {
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": f"{min_abs(template.max_space, payload.space)}Gi"}},
                "storageClassName": "standard"  # Update based on your storage setup
            }
        }
    }

    async with httpx.AsyncClient(verify=False) as client:
        response = await client.post(
            f"{KUBERNETES_API_URL}/apis/cdi.kubevirt.io/v1beta1/namespaces/{NAMESPACE}/datavolumes",
            json=datavolume_body,
            headers=HEADERS
        )

    if response.status_code != 201:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to create DataVolume: {response.text}")

    # Step 3️⃣: Wait for DataVolume to be ready
    if not await wait_for_datavolume(NAMESPACE, unique_dv_name):
        raise HTTPException(status_code=500, detail="DataVolume creation timed out")

    # Step 4️⃣: Modify VM Template to Use PVC Reference
    updated_vm_config = {
        "domain": {
            "cpu": {
                "cores": min_abs(template.max_cpu, payload.cpu)
            },
            "resources": {
                "requests": {
                "memory": f"{min_abs(template.max_ram, payload.ram)}Gi"
                }
            },
            "devices": {
                "disks": [
                {
                    "name": "rootdisk",
                    "disk": {
                    "bus": "virtio"
                    }
                },
                {
                    "name": "cloudinitdisk",
                    "disk": {
                    "bus": "virtio"
                    }
                }
                ],
                "interfaces": [
                {
                    "name": "default",
                    "bridge": {}
                }
                ]
            }
        }, 
        "networks": [{"name": "default", "multus": {"networkName": "br0"}}],  # Attach to bridge network
        "volumes": [
            {"name": "rootdisk", "persistentVolumeClaim": {"claimName": unique_dv_name}},  
            {"name": "cloudinitdisk", "cloudInitNoCloud": {"userData": "#cloud-config\npassword: " + payload.password + "\nchpasswd: { expire: False }\nssh_pwauth: True\nssh_authorized_keys:\n  - \"your-ssh-public-key-here\""}}
            #todo change password to one chosen by the user and remove ssh keys
            #todo also change username
        ]
    }

    # Step 5️⃣: Create VirtualMachine
    vm_body = {
        "apiVersion": "kubevirt.io/v1",
        "kind": "VirtualMachine",
        "metadata": {
            "name": payload.name,
            "namespace": NAMESPACE,
            "labels": {"vm_owner": str(user["id"])}
        },
        "spec": {
            "runStrategy": "Always",  # Ensures the VM runs persistently
            "template": {
                "metadata": {"labels": {"kubevirt.io/domain": payload.name}},
                "spec": updated_vm_config
            }
        }
    }

    async with httpx.AsyncClient(verify=False) as client:
        response = await client.post(
            f"{KUBERNETES_API_URL}/apis/kubevirt.io/v1/namespaces/{NAMESPACE}/virtualmachines",
            json=vm_body,
            headers=HEADERS
        )

    if response.status_code != 201:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to create VM: {response.text}")

    # Step 6️⃣: Store the VM in the database
    query = insert(vm_instances).values(
        name=payload.name,
        namespace=NAMESPACE,
        user_id=user["id"],
        template_id=payload.template_id,
        created_at=datetime.utcnow(),
    )
    vm_id = await database.execute(query)

    # Add cost logging after VM creation
    cost = calculate_cost(payload.cpu, payload.ram)
    query = insert(vm_costs).values(
        vm_instance_id=vm_id,
        cpu_cores=payload.cpu,
        ram_gb=payload.ram,
        cost_per_hour=cost,
        recorded_at=datetime.utcnow(),
    )
    await database.execute(query)

    return await get_vm(vm_id, user)


# ------------------ GET A VM ------------------
async def get_vm(id: int, user: dict) -> VirtualMachineResponse:
    """Fetch VM data from the database and verify existence in Kubernetes."""
    query = select(vm_instances).where(vm_instances.c.id == id)
    vm = await database.fetch_one(query)

    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")

    # Verify ownership
    if not user["is_admin"] and vm["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized to view this VM")

    kube_status = await check_vm_in_kube(NAMESPACE, vm["name"])
    return VirtualMachineResponse(**dict(vm), kube_status=kube_status)


# ------------------ DELETE A VM ------------------
async def delete_vm(id: int, user: dict):
    """Delete a VM from both the database and Kubernetes."""
    query = select(vm_instances).where(vm_instances.c.id == id)
    vm = await database.fetch_one(query)

    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")

    # Verify ownership
    if not user["is_admin"] and vm["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized to delete this VM")

    # Delete from Kubernetes
    url = f"{KUBERNETES_API_URL}/apis/kubevirt.io/v1/namespaces/{NAMESPACE}/virtualmachines/{vm['name']}"
    async with httpx.AsyncClient(verify=False) as client:
        await client.delete(url, headers=HEADERS)

    # Remove from DB
    query = delete(vm_instances).where(vm_instances.c.id == id)
    await database.execute(query)

    return {"message": "VM deleted successfully"}


"""# ------------------ POWER ON / OFF VM ------------------
async def power_vm(id: int, user: dict, action: str):
    query = select(vm_instances).where(vm_instances.c.id == id)
    vm = await database.fetch_one(query)

    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")

    # Verify ownership
    if not user["is_admin"] and vm["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized to manage this VM")

    # Send request to Kubernetes
    url = f"{KUBERNETES_API_URL}/apis/subresources.kubevirt.io/v1/namespaces/{NAMESPACE}/virtualmachines/{vm['name']}/{action}"
    async with httpx.AsyncClient(verify=False) as client:
        response = await client.put(url, headers=HEADERS)

    if response.status_code != 202:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to {action} VM: {response.text}")

    return {"message": f"VM {action} successfully"}


async def power_on_vm(id: int, user: dict):
    return await power_vm(id, user, "start")


async def power_off_vm(id: int, user: dict):
    return await power_vm(id, user, "stop")"""
