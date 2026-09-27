"""
SIPARTA Backend — Web3 Service Layer
======================================
Jembatan Python Native ke Polygon Amoy.

Menggunakan PolygonAmoyClient untuk menjalankan transaksi secara langsung
tanpa dependensi eksternal Node.js (Render Native Python Support).
"""

import logging
import sys
import os
from pathlib import Path

logger = logging.getLogger("siparta.web3_service")

try:
    from services.blockchain.polygon_client import PolygonAmoyClient, BlockchainError
except ImportError as e:
    logger.error(f"[WEB3] Gagal import PolygonAmoyClient: {e}")
    PolygonAmoyClient = None

import asyncio

async def log_incident_to_blockchain(payload: dict) -> dict:
    """
    Mencatat insiden ke Polygon Amoy via native Python client.
    """
    if PolygonAmoyClient is None:
        logger.error("[WEB3] Client tidak tersedia, return error.")
        return {"txHash": None, "blockNumber": 0, "mode": "error"}

    try:
        # Pindahkan pemanggilan blocking ke background thread
        def _anchor():
            client = PolygonAmoyClient()
            incident_id = payload.get("incident_id")
            if not incident_id:
                raise ValueError("incident_id is missing from payload")
            return client.anchor_incident(incident_id, payload)
            
        result = await asyncio.to_thread(_anchor)
        
        return {
            "txHash": result.get("transaction_hash"),
            "blockNumber": result.get("block_number"),
            "ipfsCid": result.get("ipfs_cid"),
            "mode": "primary"
        }
    except Exception as e:
        logger.error(f"[WEB3] Gagal anchoring incident: {e}")
        # Try to extract ipfs_cid from exception if we threw it after pinata upload
        # But polygon_client.py doesn't attach ipfs_cid to the exception.
        # Let's modify polygon_client.py instead.
        return {"txHash": None, "blockNumber": 0, "ipfsCid": None, "mode": "error"}

async def verify_incident_on_chain(incident_uuid: str) -> bool:
    """
    Verifikasi apakah insiden sudah tercatat di SipartaAudit contract.
    """
    if PolygonAmoyClient is None:
        logger.error("[WEB3] Client tidak tersedia, return False.")
        return False

    try:
        def _verify():
            client = PolygonAmoyClient()
            return client.verify_incident(incident_uuid)
            
        return await asyncio.to_thread(_verify)
    except Exception as e:
        logger.error(f"[WEB3] Gagal verify_incident_on_chain: {e}")
        return False
