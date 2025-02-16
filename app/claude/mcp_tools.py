import httpx
from pydantic import BaseModel, Field
from typing import Optional, List

KUBERNETES_API_URL = "https://ip"  # Replace with actual endpoint
HEADERS = {"Authorization": f"Bearer token"}




async def list_vms(user: str, namespace: str = "default"):
    # Fetch VMs from the Kubernetes API
    url = f"{KUBERNETES_API_URL}/apis/kubevirt.io/v1/namespaces/{namespace}/virtualmachines"
    async with httpx.AsyncClient(verify=False) as client:
        response = await client.get(url, headers=HEADERS)
        if response.status_code != 200:
            return {"error": response.text}

    # Parse the response and map it to the expected schema
    vms = response.json().get("items", [])
    result = []
    
    for vm in vms:
        metadata = vm.get("metadata", {})
        spec = vm.get("spec", {})
        status = vm.get("status", {})
        template_spec = spec.get("template", {}).get("spec", {})
        domain = template_spec.get("domain", {})
        resources = domain.get("resources", {}).get("requests", {})
        networks = template_spec.get("networks", [])
        disks = domain.get("devices", {}).get("disks", [])
        volumes = template_spec.get("volumes", [])

        # Map the data to the simplified schema
        result.append({
            "name": metadata.get("name"),
            "namespace": metadata.get("namespace"),
            "uid": metadata.get("uid"),
            "creationTimestamp": metadata.get("creationTimestamp"),
            "architecture": template_spec.get("architecture", "Unknown"),
            "memory": resources.get("memory", "Unknown"),
            "status": status.get("printableStatus", "Unknown"),
            "networks": [{"name": n.get("name")} for n in networks],
            "disks": [{"name": d.get("name"), "bus": d.get("disk", {}).get("bus")} for d in disks],
            "volumes": [
                {
                    "name": v.get("name"),
                    "containerDiskImage": v.get("containerDisk", {}).get("image")
                }
                for v in volumes
            ],
        })
    
    return result
