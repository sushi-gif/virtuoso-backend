import asyncio
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types
from mcp_tools import list_vms, list_templates, get_vm_metrics, get_vm_costs, update_vm
import httpx  # Add this import

server = Server("virtuoso-server")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list-vms",
            description="List accessible virtual machines",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
                "x-auth-context": True
            }
        ),
        types.Tool(
            name="list-templates",
            description="List available VM templates",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
                "x-auth-context": True
            }
        ),
        types.Tool(
            name="get-vm-metrics",
            description="Get metrics for a VM",
            inputSchema={
                "type": "object",
                "properties": {
                    "vm_id": {"type": "integer", "description": "VM ID (optional)"}
                },
                "required": [],
                "x-auth-context": True
            }
        ),
        types.Tool(
            name="get-vm-costs",
            description="Get cost history for a VM",
            inputSchema={
                "type": "object",
                "properties": {
                    "vm_id": {"type": "integer", "description": "VM ID"}
                },
                "required": ["vm_id"],
                "x-auth-context": True
            }
        ),
        types.Tool(
            name="update-vm",
            description="Update a VM's CPU and RAM allocation",
            inputSchema={
                "type": "object",
                "properties": {
                    "vm_id": {"type": "integer", "description": "VM ID to update"},
                    "cpu": {"type": "integer", "description": "New CPU core count"},
                    "ram": {"type": "integer", "description": "New RAM allocation in GB"}
                },
                "required": ["vm_id", "cpu", "ram"],
                "x-auth-context": True
            }
        )
    ]



# Update handle_call_tool function in mcp_server.py
@server.call_tool()
async def handle_call_tool(
    name: str,
    arguments: dict | None
) -> list[types.TextContent]:
    token = (arguments or {}).get("_auth_token", "")
    
    try:
        clean_args = {k: v for k, v in (arguments or {}).items() if not k.startswith("_")}
        
        if name == "list-templates":
            templates = await list_templates(token)
            return [types.TextContent(
                type="text", 
                text=format_templates(templates) if templates else "No templates found"
            )]
            
        elif name == "list-vms":
            vms = await list_vms(token)
            return [types.TextContent(
                type="text",
                text=format_vms(vms) if vms else "No VMs found"
            )]
            
        elif name == "get-vm-metrics":
            vm_id = clean_args.get("vm_id")
            metrics = await get_vm_metrics(token, vm_id)
            return [types.TextContent(
                type="text",
                text=format_metrics(metrics) if metrics else "No metrics available"
            )]
            
        elif name == "get-vm-costs":
            vm_id = clean_args.get("vm_id")
            if not vm_id:
                return [types.TextContent(
                    type="text",
                    text="VM ID is required"
                )]
            costs = await get_vm_costs(token, vm_id)
            return [types.TextContent(
                type="text",
                text=format_costs(costs) if costs else "No cost records"
            )]
            
        elif name == "update-vm":
            vm_id = clean_args.get("vm_id")
            cpu = clean_args.get("cpu")
            ram = clean_args.get("ram")
            
            if not all([vm_id, cpu, ram]):
                return [types.TextContent(
                    type="text",
                    text="Missing required parameters: vm_id, cpu, or ram"
                )]
            
            result = await update_vm(token, vm_id, cpu, ram)
            return [types.TextContent(
                type="text",
                text=format_update_result(result) if result else "Update failed"
            )]

        else:
            return [types.TextContent(
                type="text",
                text=f"Unknown tool: {name}"
            )]
            
    except RuntimeError as e:
        return [types.TextContent(
            type="text",
            text=f"Error: {str(e)}"
        )]
    except Exception as e:
        return [types.TextContent(
            type="text",
            text=f"Unexpected Error: {str(e)}"
        )]
        
def format_vms(vms):
    if not vms or not isinstance(vms, list):
        return "No virtual machines found"
    
    formatted = []
    for vm in vms:
        try:
            entry = (
                f"{vm.get('name', 'Unknown')} "
                f"(ID: {vm.get('id', 'N/A')}) | "
                f"Status: {vm.get('kube_status', {}).get('status', 'unknown')}"
            )
            formatted.append(entry)
        except Exception as e:
            continue
            
    return "\n".join(formatted) if formatted else "No virtual machines available"

def format_templates(templates):
    return "\n".join([f"{t['name']} | MAX. CPU: {t['max_cpu']} | MAX. RAM: {t['max_ram']}GB"
                     for t in templates])

def format_metrics(metrics):
    return "\n".join([f"{m.get('vm_name', '') } | CPU: {m['cpu_usage']} | RAM: {m['memory_usage']}"
                     for m in metrics])

def format_costs(costs):
    """Completely null-safe formatting"""
    try:
        # Force valid input type
        safe_costs = []
        if isinstance(costs, list):
            safe_costs = [c for c in costs if isinstance(c, dict)]
        elif isinstance(costs, dict):
            safe_costs = [costs]
            
        if not safe_costs:
            return "No cost records available"
            
        return "\n".join([
            f"{c.get('recorded_at', 'Unknown date')} | "
            f"CPU: {c.get('cpu_cores', 0)} | "
            f"RAM: {c.get('ram_gb', 0)}GB | "
            f"Cost: ${float(c.get('cost_per_hour', 0))/100:.2f}/hr"
            for c in safe_costs
        ])
    except Exception as e:
        return "Unable to format cost data"

# Add to mcp_server.py
def format_update_result(result):
    if not isinstance(result, dict):
        return "Invalid update response"
    
    status = result.get('kube_status', {}).get('status', 'unknown')
    return (
        f"VM {result.get('id', 'unknown')} ({result.get('name', 'unnamed')}) updated\n"
        f"CPU: {result.get('kube_status', {}).get('cores', 'N/A')} cores\n"
        f"RAM: {result.get('kube_status', {}).get('memory', 'N/A')}\n"
        f"Current Status: {status}"
    )

async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="virtuoso-server",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                )
            )
        )

if __name__ == "__main__":
    asyncio.run(main())