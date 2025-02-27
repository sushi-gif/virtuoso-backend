import httpx
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)
FASTAPI_URL = "http://localhost:8000"

# Modify api_request in mcp_tools.py
async def api_request(method: str, endpoint: str, token: str, payload: Optional[dict] = None) -> List[Dict[str, Any]]:
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.request(
                method,
                f"{FASTAPI_URL}{endpoint}",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list):
                return data
            else:
                return [data] if data else []
            
    except httpx.HTTPStatusError as e:
        logger.error(f"API Error {e.response.status_code}: {e.response.text}")
        raise RuntimeError(f"API Error {e.response.status_code}")
    except Exception as e:
        logger.error(f"Connection Error: {str(e)}")
        raise RuntimeError("Connection failed")

# Update get_vm_metrics in mcp_tools.py
async def get_vm_metrics(token: str, vm_id: Optional[int] = None) -> List[Dict[str, Any]]:
    if vm_id:
        endpoint = f"/vms/{vm_id}/metrics"
    else:
        endpoint = "/vms/metrics"
    return await api_request("GET", endpoint, token)

async def list_vms(token: str) -> List[Dict[str, Any]]:
    return await api_request("GET", "/vms", token)  # Added trailing slash

async def list_templates(token: str) -> List[Dict[str, Any]]:
    return await api_request("GET", "/templates", token)  # Added trailing slash



async def get_vm_costs(token: str, vm_id: int) -> List[Dict[str, Any]]:
    return await api_request("GET", f"/vms/{vm_id}/costs/", token)

# Add to mcp_tools.py
async def update_vm(token: str, vm_id: int, cpu: int, ram: int) -> Dict[str, Any]:
    endpoint = f"/vms/{vm_id}"
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.patch(
                f"{FASTAPI_URL}{endpoint}",
                headers={"Authorization": f"Bearer {token}"},
                json={"cpu": cpu, "ram": ram},
                timeout=10
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Update Error {e.response.status_code}: {e.response.text}")
        raise RuntimeError(f"Update failed: {e.response.text}")
    except Exception as e:
        logger.error(f"Connection Error: {str(e)}")
        raise RuntimeError("Connection failed during update")