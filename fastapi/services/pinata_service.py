import os
import requests
import logging

logger = logging.getLogger("siparta.pinata")

PINATA_JWT = os.getenv("PINATA_JWT")

def upload_json_to_ipfs(metadata: dict, name: str = 'siparta-incident-metadata.json') -> str:
    """
    Uploads a JSON object to Pinata IPFS.
    """
    if not PINATA_JWT:
        logger.error("PINATA_JWT is not defined in environment variables.")
        raise ValueError("PINATA_JWT is not defined in environment variables.")

    url = 'https://api.pinata.cloud/pinning/pinJSONToIPFS'
    
    payload = {
        "pinataOptions": {
            "cidVersion": 1
        },
        "pinataMetadata": {
            "name": name,
        },
        "pinataContent": metadata
    }
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {PINATA_JWT}'
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        if 'IpfsHash' not in data:
            raise ValueError("Invalid response from Pinata: missing IpfsHash")
            
        logger.info(f"[PINATA] Successfully uploaded to IPFS: {data['IpfsHash']}")
        return data['IpfsHash']
    except requests.exceptions.RequestException as e:
        logger.error(f"[PINATA] Failed to upload JSON to IPFS: {e}")
        if e.response:
            logger.error(f"Response: {e.response.text}")
        raise
