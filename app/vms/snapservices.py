import uuid
import asyncio
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import insert, select, delete
from app.db.database import database
from app.db.models import vm_instances, vm_snapshots, users
from app.core.variables import KUBERNETES_API_URL, HEADERS
from app.core.security import verify_token
from app.vms.schemas import VMSnapshot  # Ensure this schema is updated as needed

# ------------------ Helper: Fetch VM from DB (and verify ownership) ------------------
async def fetch_vm_from_db(vm_id: int, user: dict):
    query = select(vm_instances).where(vm_instances.c.id == vm_id)
    vm = await database.fetch_one(query)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    if not user["is_admin"] and vm["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized for this VM")
    return dict(vm)

# ------------------ SNAPSHOT FUNCTIONS ------------------

async def create_snapshot(vm_id: int, user: dict) -> VMSnapshot:
    """
    Create a new snapshot for a VM.
    
    Steps:
    1. Verify VM ownership in DB.
    2. Generate a unique snapshot name.
    3. Create the snapshot in Kubernetes.
    4. Insert the snapshot record into the database.
    5. Return snapshot details.
    """
    vm = await fetch_vm_from_db(vm_id, user)

    # Generate a unique snapshot name (e.g., snap-<uuid>)
    snapshot_name = f"{vm['name']}-snap-{uuid.uuid4().hex[:6]}"

    # Create snapshot manifest for Kubernetes
    snapshot_manifest = {
        "apiVersion": "snapshot.kubevirt.io/v1alpha1",
        "kind": "VirtualMachineSnapshot",
        "metadata": {
            "name": snapshot_name,
            "namespace": vm["namespace"]
        },
        "spec": {
            "source": {
                "kind": "VirtualMachine",
                "name": vm["name"],
                "namespace": vm["namespace"],
                "apiGroup": "kubevirt.io"
            }
        }
    }

    async with httpx.AsyncClient(verify=False) as client:
        kube_response = await client.post(
            f"{KUBERNETES_API_URL}/apis/snapshot.kubevirt.io/v1alpha1/namespaces/{vm['namespace']}/virtualmachinesnapshots",
            json=snapshot_manifest,
            headers=HEADERS
        )

    if kube_response.status_code != 201:
        raise HTTPException(
            status_code=kube_response.status_code,
            detail=f"Failed to create snapshot in Kubernetes: {kube_response.text}"
        )

    # Insert snapshot record into the database
    insert_query = insert(vm_snapshots).values(
        vm_instance_id=vm["id"],
        snapshot_name=snapshot_name,
        created_at=datetime.utcnow()
    )
    snapshot_id = await database.execute(insert_query)

    # Return snapshot details with the proper ID from the DB
    return VMSnapshot(
        id=snapshot_id,  # The ID now comes from the database
        name=snapshot_name,
        namespace=vm["namespace"],
        creationTimestamp=datetime.utcnow().isoformat(),
    )


async def get_snapshots(vm_id: int, user: dict) -> list[VMSnapshot]:
    """
    List all snapshots for a given VM.
    
    For each snapshot stored in the DB, query Kubernetes to fetch its current status.
    """
    vm = await fetch_vm_from_db(vm_id, user)

    # Get snapshot records from DB
    query = select(vm_snapshots).where(vm_snapshots.c.vm_instance_id == vm["id"])
    snapshot_records = await database.fetch_all(query)

    snapshots = []
    async with httpx.AsyncClient(verify=False) as client:
        for record in snapshot_records:
            snapshot_name = record["snapshot_name"]
            url = f"{KUBERNETES_API_URL}/apis/snapshot.kubevirt.io/v1alpha1/namespaces/{vm['namespace']}/virtualmachinesnapshots/{snapshot_name}"
            kube_response = await client.get(url, headers=HEADERS)
            if kube_response.status_code == 200:
                snap_data = kube_response.json()
                creation_ts = snap_data.get("metadata", {}).get("creationTimestamp")
            else:
                creation_ts = None
            

            snapshots.append(VMSnapshot(
                id=record["id"],
                name=snapshot_name,
                namespace=vm["namespace"],
                creationTimestamp=creation_ts,
            ))
    return snapshots


async def get_snapshot_details(vm_id: int, snap_id: int, user: dict) -> VMSnapshot:
    """
    Get details of a specific snapshot.
    
    Steps:
    1. Verify the snapshot exists in the database using its ID.
    2. Use the stored snapshot_name to query Kubernetes.
    3. Return the snapshot details.
    """
    vm = await fetch_vm_from_db(vm_id, user)

    # Verify snapshot exists in DB using its primary key (snap_id)
    query = select(vm_snapshots).where(vm_snapshots.c.id == snap_id)
    record = await database.fetch_one(query)
    if not record:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    snapshot_name = record["snapshot_name"]
    url = f"{KUBERNETES_API_URL}/apis/snapshot.kubevirt.io/v1alpha1/namespaces/{vm['namespace']}/virtualmachinesnapshots/{snapshot_name}"
    async with httpx.AsyncClient(verify=False) as client:
        kube_response = await client.get(url, headers=HEADERS)

    if kube_response.status_code != 200:
        raise HTTPException(
            status_code=kube_response.status_code,
            detail=f"Failed to fetch snapshot from Kubernetes: {kube_response.text}"
        )

    snap_data = kube_response.json()
    return VMSnapshot(
        id=record["id"],
        name=snap_data["metadata"]["name"],
        namespace=vm["namespace"],
        creationTimestamp=snap_data["metadata"].get("creationTimestamp"),
    )


async def delete_snapshot(vm_id: int, snap_id: int, user: dict):
    """
    Delete a snapshot.
    
    Steps:
    1. Verify the snapshot exists in the database using its ID.
    2. Delete the snapshot from Kubernetes.
    3. Delete the record from the DB.
    """
    vm = await fetch_vm_from_db(vm_id, user)

    # Verify snapshot exists in DB using its primary key (snap_id)
    query = select(vm_snapshots).where(vm_snapshots.c.id == snap_id)
    record = await database.fetch_one(query)
    if not record:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    snapshot_name = record["snapshot_name"]
    url = f"{KUBERNETES_API_URL}/apis/snapshot.kubevirt.io/v1alpha1/namespaces/{vm['namespace']}/virtualmachinesnapshots/{snapshot_name}"
    async with httpx.AsyncClient(verify=False) as client:
        kube_response = await client.delete(url, headers=HEADERS)

    if kube_response.status_code not in (200, 202, 204):
        raise HTTPException(
            status_code=kube_response.status_code,
            detail=f"Failed to delete snapshot from Kubernetes: {kube_response.text}"
        )

    # Delete snapshot record from the database
    delete_query = delete(vm_snapshots).where(vm_snapshots.c.id == snap_id)
    await database.execute(delete_query)

    return {"message": f"Snapshot {snapshot_name} deleted successfully"}
