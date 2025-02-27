from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from app.db.database import database
from app.db.models import users, vm_instances, templates, vm_costs
from app.core.security import verify_token, ws_token_to_jwt
from app.vms.schemas import *
from app.vms.services import *
from app.vms.snapservices import *
from typing import List, Optional
from datetime import datetime
import httpx
import aiohttp
import asyncio
import re

router = APIRouter()

# ------------------ Metrics Parsing Helpers ------------------
def parse_cpu_usage(cpu_str: str) -> int:
    """
    Convert CPU usage string to millicores as integer.
    E.g., "500m" -> 500, "1" -> 1000.
    """
    if cpu_str.endswith("m") or cpu_str.endswith("n"):
        return int(cpu_str[:-1])
    else:
        return int(float(cpu_str) * 1000)

def parse_memory_usage(mem_str: str) -> int:
    """
    Convert memory usage string to Ki (integer).
    E.g., "256Mi" -> 256*1024, "1Gi" -> 1*1024*1024.
    """
    if mem_str.endswith("Ki"):
        return int(mem_str[:-2])
    elif mem_str.endswith("Mi"):
        return int(mem_str[:-2]) * 1024
    elif mem_str.endswith("Gi"):
        return int(mem_str[:-2]) * 1024 * 1024
    else:
        # fallback: assume value is already in Ki
        return int(mem_str)


class NodeMetrics(BaseModel):
    node_name: str
    cpu_usage: str  # e.g., "500m"
    memory_usage: str  # e.g., "1Gi"



class VMMetrics(BaseModel):
    cpu_usage: str  # e.g., "100m"
    memory_usage: str  # e.g., "256Mi"

async def get_vm_pod_name(namespace: str, vm_name: str) -> str:
    """
    Fetch the pod name for a VM by querying Kubernetes with the correct label selector.
    """
    url = f"{KUBERNETES_API_URL}/api/v1/namespaces/{namespace}/pods"
    params = {"labelSelector": f"vm.kubevirt.io/name={vm_name}"}
    async with httpx.AsyncClient(verify=False) as client:
        response = await client.get(url, headers=HEADERS, params=params)

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch VM pod")

    pods = response.json().get("items", [])
    if not pods:
        raise HTTPException(status_code=404, detail=f"No pod found for VM {vm_name}")

    return pods[0]["metadata"]["name"]



async def fetch_k8s_vm_metrics(namespace: str, vm_name: str) -> VMMetrics:
    """
    Fetch metrics for a VM pod using Metrics Server.
    """
    try:
        pod_name = await get_vm_pod_name(namespace, vm_name)
    except HTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=f"Failed to fetch VM pod: {e.detail}")

    metrics_url = f"{KUBERNETES_API_URL}/apis/metrics.k8s.io/v1beta1/namespaces/{namespace}/pods/{pod_name}"
    async with httpx.AsyncClient(verify=False) as client:
        metrics_response = await client.get(metrics_url, headers=HEADERS)

    if metrics_response.status_code != 200:
        raise HTTPException(status_code=metrics_response.status_code, detail="Metrics unavailable")

    metrics_data = metrics_response.json()
    containers = metrics_data.get("containers", [])

    # Sum usage across all containers in the pod using the new helpers
    total_cpu = sum(parse_cpu_usage(c["usage"]["cpu"]) for c in containers)
    total_memory_ki = sum(parse_memory_usage(c["usage"]["memory"]) for c in containers)

    # Format the CPU and memory usage strings
    cpu_usage_str = f"{total_cpu}m"
    memory_usage_str = f"{total_memory_ki // 1024}Mi"

    return VMMetrics(
        cpu_usage=cpu_usage_str,
        memory_usage=memory_usage_str
    )

# Add new response model
class VMMetricItem(VMMetrics):
    vm_id: int
    vm_name: str

# ------------------ Helper: Fetch User from DB ------------------
async def get_user_from_token(decoded_token: dict):
    """Fetch user details from DB based on JWT token (sub=username)."""
    query = users.select().where(users.c.username == decoded_token["sub"])
    user = await database.fetch_one(query)

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return dict(user)  # Convert row to dictionary


# ------------------ LIST VMs ------------------
@router.get("/", response_model=List[VirtualMachineResponse])
async def list_vms_endpoint(token=Depends(verify_token)):
    """List all VM instances from DB and check their status in Kubernetes."""
    user = await get_user_from_token(token)
    return await list_vms(user)


# ------------------ CREATE A VM ------------------
@router.post("/", response_model=VirtualMachineResponse)
async def create_vm_endpoint(vm: CreateVM, token=Depends(verify_token)):
    """Create a new Virtual Machine based on a template."""
    user = await get_user_from_token(token)
    return await create_vm(vm, user)
    
    



@router.get("/nodemetrics", response_model=List[NodeMetrics])
async def get_node_metrics(token=Depends(verify_token)):
    """
    Fetch metrics for all nodes in the cluster.
    """
    user = await get_user_from_token(token)
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Only admins can view node metrics")

    metrics_url = f"{KUBERNETES_API_URL}/apis/metrics.k8s.io/v1beta1/nodes"
    async with httpx.AsyncClient(verify=False) as client:
        metrics_response = await client.get(metrics_url, headers=HEADERS)

    if metrics_response.status_code != 200:
        raise HTTPException(status_code=metrics_response.status_code, detail="Failed to fetch node metrics")

    metrics_data = metrics_response.json()
    node_metrics = []

    for node in metrics_data["items"]:
        node_metrics.append(NodeMetrics(
            node_name=node["metadata"]["name"],
            cpu_usage=node["usage"]["cpu"],
            memory_usage=node["usage"]["memory"]
        ))

    return node_metrics


# Update the VMMetricItem model
class VMMetricItem(VMMetrics):
    vm_id: int
    vm_name: str
    last_cost: Optional[int] = None
    last_cost_timestamp: Optional[datetime] = None

# Modified metrics endpoint
@router.get("/metrics", response_model=List[VMMetricItem])
async def get_vm_metrics_list(token=Depends(verify_token)):
    """
    Get metrics for all VMs owned by the current user
    (returns all VMs if user is admin)
    """
    user = await get_user_from_token(token)
    vms_list = await list_vms(user)
    
    metrics_list = []
    
    for vm in vms_list:
        # Filter VMs for non-admins
        if not user["is_admin"] and vm.user_id != user["id"]:
            continue
            
        try:
            vm_metrics = await fetch_k8s_vm_metrics(vm.namespace, vm.name)
            
            # Get latest cost record
            query = vm_costs.select().where(vm_costs.c.vm_instance_id == vm.id)\
                        .order_by(vm_costs.c.recorded_at.desc()).limit(1)
            cost_record = await database.fetch_one(query)
            
            metrics_list.append(VMMetricItem(
                vm_id=vm.id,
                vm_name=vm.name,
                cpu_usage=vm_metrics.cpu_usage,
                memory_usage=vm_metrics.memory_usage,
                last_cost=cost_record.cost_per_hour if cost_record else None,
                last_cost_timestamp=cost_record.recorded_at if cost_record else None
            ))
        except HTTPException as e:
            print(f"Skipping VM {vm.name} due to error: {e.detail}")
        except Exception as e:
            print(f"Unexpected error with VM {vm.name}: {str(e)}")
    
    return metrics_list


# ------------------ GET A VM ------------------
@router.get("/{id}", response_model=VirtualMachineResponse)
async def get_vm_endpoint(id: int, token=Depends(verify_token)):
    """Fetch VM data from DB and verify its existence in Kubernetes."""
    user = await get_user_from_token(token)
    return await get_vm(id, user)

# ------------------ DELETE A VM ------------------
@router.delete("/{id}")
async def delete_vm_endpoint(id: int, token=Depends(verify_token)):
    """Delete a VM from both DB and Kubernetes."""
    user = await get_user_from_token(token)
    return await delete_vm(id, user)

@router.patch("/{id}", response_model=VirtualMachineResponse)
async def patch_vm_endpoint(id: int, vm_patch: PatchVM, token=Depends(verify_token)):
    """Patch the resources of a VM instance. Only the VM owner or an admin can modify it."""
    # Fetch user
    user = await get_user_from_token(token)

    # Fetch VM data
    query = select(vm_instances).where(vm_instances.c.id == id)
    vm = await database.fetch_one(query)

    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")

    # Check if the user is an admin or the owner of the VM
    if not user["is_admin"] and vm["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized to edit this VM")

    # Fetch the template to get max resources
    template_query = select(templates).where(templates.c.id == vm["template_id"])
    template = await database.fetch_one(template_query)

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # Apply resource constraints using the min_abs function
    updated_cpu = min_abs(template["max_cpu"], vm_patch.cpu) if vm_patch.cpu else vm["cpu"]
    updated_ram = min_abs(template["max_ram"], vm_patch.ram) if vm_patch.ram else vm["ram"]

    # Step 1: Fetch the current VM configuration from Kubernetes
    url = f"{KUBERNETES_API_URL}/apis/kubevirt.io/v1/namespaces/{vm.namespace}/virtualmachines/{vm.name}"
    async with httpx.AsyncClient(verify=False) as client:
        response = await client.get(url, headers=HEADERS)

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch VM from Kubernetes: {response.text}")
    
    current_vm = response.json()
    resource_version = current_vm['metadata']['resourceVersion']  # Get the current resourceVersion

    # Step 2: Prepare the updated VM configuration, preserving the existing devices, volumes, etc.
    updated_vm_config = {
        "apiVersion": "kubevirt.io/v1",  # Set the API version to kubevirt.io/v1
        "kind": "VirtualMachine",  # Define the kind of the resource
        "metadata": {
            "name": vm["name"],  # Ensure the VM name is included in the metadata
            "namespace": vm["namespace"],  # Include the namespace
            "resourceVersion": resource_version  # Include the resourceVersion here
        },
        "spec": {
            "running": True,  # Ensure the VM is running after the update, or set to False to stop
            "template": {
                "spec": {
                    "domain": {
                        "cpu": {
                            "cores": updated_cpu  # Update CPU cores
                        },
                        "resources": {
                            "requests": {
                                "memory": f"{updated_ram}Gi"  # Update RAM in Gi
                            }
                        },
                        "devices": current_vm['spec']['template']['spec']['domain'].get('devices', []),  # Preserve devices
                    },
                    # Preserve the rest of the spec (volumes, networks, etc.)
                    "networks": current_vm['spec']['template']['spec'].get('networks', []),  # Attach to bridge network
                    "volumes": current_vm['spec']['template']['spec'].get('volumes', []),
                }
            }
        }
    }

    # Step 3: Update the VM in Kubernetes
    async with httpx.AsyncClient(verify=False) as client:
        response = await client.put(url, json=updated_vm_config, headers=HEADERS)
        print(response.text)

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to update VM in Kubernetes: {response.text}")

    # Step 4: Restart the VM by triggering a restart operation using KubeVirt API
    # Step 1: Create the API URL to restart the VM
    print(vm)
    restart_url = f"{KUBERNETES_API_URL}/apis/subresources.kubevirt.io/v1/namespaces/{vm['namespace']}/virtualmachines/{vm['name']}/restart"

    # Step 2: Restart the VM (POST request)
    async with httpx.AsyncClient(verify=False) as client:
        restart_response = await client.put(restart_url, headers=HEADERS)

    # Step 3: Check for any issues with the restart request
    if restart_response.status_code != 202:
        raise HTTPException(status_code=restart_response.status_code, detail=f"Failed to restart VM in Kubernetes: {restart_response.text}")


    # Add cost logging after resource update
    cost = calculate_cost(updated_cpu, updated_ram)
    query = insert(vm_costs).values(
        vm_instance_id=id,
        cpu_cores=updated_cpu,
        ram_gb=updated_ram,
        cost_per_hour=cost,
        recorded_at=datetime.utcnow(),
    )
    await database.execute(query)

    # Step 5: Return the updated VM details
    kube_status = await check_vm_in_kube(vm["namespace"], vm["name"])
    return VirtualMachineResponse(**dict(vm), kube_status=kube_status)


@router.post("/{vm_id}/snapshots/", response_model=VMSnapshot)
async def create_vm_snapshot(vm_id: int, token=Depends(verify_token)):
    """
    Create a snapshot for a given VM. The snapshot is created in Kubernetes and recorded in the DB.
    """
    user = await get_user_from_token(token)
    snapshot = await create_snapshot(vm_id, user)
    return snapshot


@router.get("/{vm_id}/snapshots/", response_model=list[VMSnapshot])
async def list_vm_snapshots(vm_id: int, token=Depends(verify_token)):
    """
    List all snapshots for a given VM. Each snapshot’s status is fetched from Kubernetes.
    """
    user = await get_user_from_token(token)
    snapshots = await get_snapshots(vm_id, user)
    return snapshots


@router.get("/{vm_id}/snapshots/{snap_id}", response_model=VMSnapshot)
async def get_vm_snapshot(vm_id: int, snap_id: int, token=Depends(verify_token)):
    """
    Get detailed information about a specific snapshot by its database ID.
    """
    user = await get_user_from_token(token)
    snapshot = await get_snapshot_details(vm_id, snap_id, user)
    return snapshot


@router.delete("/{vm_id}/snapshots/{snap_id}", response_model=dict)
async def delete_vm_snapshot(vm_id: int, snap_id: int, token=Depends(verify_token)):
    """
    Delete a specific snapshot by its database ID from Kubernetes and remove its record from the database.
    """
    user = await get_user_from_token(token)
    result = await delete_snapshot(vm_id, snap_id, user)
    return result


class VMCostRecord(BaseModel):
    recorded_at: datetime | None
    cpu_cores: int
    ram_gb: int
    cost_per_hour: int

@router.get("/{id}/costs", response_model=List[VMCostRecord])
async def get_vm_costs(id: int, token=Depends(verify_token)):
    print(f"incoming req with id {id}")
    user = await get_user_from_token(token)
    vm = await get_vm(id, user)  # Reuse existing auth check
    
    query = vm_costs.select().where(vm_costs.c.vm_instance_id == id)
    records = await database.fetch_all(query)
    
    return [dict(record) for record in records] if records else []


class SocketProxyInfo(BaseModel):
    proxyUrl: str  # WebSocket URL for VNC connection
    expiresIn: int  # Time in seconds until the URL expires




@router.websocket("/{id}/vnc-proxy")
async def websocket_vnc_proxy(websocket: WebSocket, id: int):
    """
    WebSocket proxy for VNC connections to Kubernetes.
    """
    await websocket.accept()

    # Extract and validate the token
    query_params = websocket.query_params
    token = ws_token_to_jwt(str(query_params).split("=")[1])
    user = await get_user_from_token(token)

    # Fetch VM details
    vm = await get_vm(id, user)
    if not vm:
        await websocket.close(code=1008, reason="VM not found")
        return

    # Kubernetes WebSocket URL
    k8s_ws_url = f"{KUBERNATES_WS_URL}/apis/subresources.kubevirt.io/v1/namespaces/{vm.namespace}/virtualmachineinstances/{vm.name}/vnc"

    headers = {
        "Authorization": f"Bearer {token}"  # Include token in headers if required
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(k8s_ws_url, headers=headers) as k8s_websocket:
                print("Connection open")

                # Proxy messages between client and Kubernetes
                await asyncio.gather(
                    _proxy_messages_from_fastapi(websocket, k8s_websocket),
                    _proxy_messages_from_k8s(k8s_websocket, websocket)
                )
    except Exception as e:
        print(f"WebSocket proxy error: {e}")
    finally:
        await websocket.close()
        print("Connection closed")


async def _proxy_messages_from_fastapi(source: WebSocket, destination: aiohttp.ClientWebSocketResponse):
    """
    Proxy messages from FastAPI WebSocket to Kubernetes WebSocket.
    """
    try:
        while True:
            message = await source.receive()
            if "text" in message:
                await destination.send_str(message["text"])
            elif "bytes" in message:
                await destination.send_bytes(message["bytes"])
            elif "ping" in message:
                await destination.ping()
            elif "pong" in message:
                await destination.pong()
            elif "close" in message:
                await destination.close()
                break  # Exit loop on close
    except WebSocketDisconnect:
        print("FastAPI WebSocket disconnected")
    except Exception as e:
        print(f"Error proxying messages from FastAPI to K8s: {e}")


async def _proxy_messages_from_k8s(source: aiohttp.ClientWebSocketResponse, destination: WebSocket):
    """
    Proxy messages from Kubernetes WebSocket to FastAPI WebSocket.
    """
    try:
        async for message in source:
            if message.type == aiohttp.WSMsgType.TEXT:
                await destination.send_text(message.data)
            elif message.type == aiohttp.WSMsgType.BINARY:
                await destination.send_bytes(message.data)
            elif message.type == aiohttp.WSMsgType.PING:
                await destination.send_bytes(b'\x89')
            elif message.type == aiohttp.WSMsgType.PONG:
                await destination.send_bytes(b'\x8A')
            elif message.type == aiohttp.WSMsgType.CLOSE:
                await destination.close()
                break  # Exit loop on close
    except Exception as e:
        print(f"Error proxying messages from K8s to FastAPI: {e}")

class VMI(BaseModel):
    macAddress: str
    ipv4Address: str
    name: str


@router.get("/{id}/vmi", response_model=VMI)
async def get_vmi(id: int, token=Depends(verify_token)):
    """
    Fetch the IP address of a VM from Kubernetes.
    """
    user = await get_user_from_token(token)
    vm = await get_vm(id, user)  # Reuse existing auth check

    # Kubernetes API URL to get the VirtualMachineInstance (VMI) status
    url = f"{KUBERNETES_API_URL}/apis/kubevirt.io/v1/namespaces/{vm.namespace}/virtualmachineinstances/{vm.name}"
    
    async with httpx.AsyncClient(verify=False) as client:
        response = await client.get(url, headers=HEADERS)

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch VM IP: {response.text}")
    
    vmi_status = response.json()
    interfaces = vmi_status.get("status", {}).get("interfaces", [])

    
    if not interfaces:
        raise HTTPException(status_code=404, detail="No network interfaces found for VM")
    
    return {
        "name": interfaces[0].get("name"),
        "macAddress": interfaces[0].get("mac"),
        "ipv4Address": interfaces[0].get("ipAddress")
        }



####
@router.get("/{id}/metrics", response_model=VMMetrics)  # This comes AFTER
async def get_single_vm_metrics(id: int, token=Depends(verify_token)):
    """
    Get metrics for a specific VM by ID
    """
    user = await get_user_from_token(token)
    vm = await get_vm(id, user)
    
    # Verify ownership for non-admins
    if not user["is_admin"] and vm.user_id != user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized to view this VM")
    
    return await fetch_k8s_vm_metrics(vm.namespace, vm.name)