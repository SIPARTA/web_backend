"""Web3 client for storing gas-detection records on Polygon Amoy.

Responsibilities
----------------
* connect to a configurable RPC endpoint,
* verify chain ID, wallet and deployed contract bytecode,
* build / sign / send ``addData`` transactions (EIP-1559 with legacy
  fallback),
* wait for receipts, decode ``DataStored`` events,
* translate raw web3 errors into typed exceptions.

Security: the private key lives only in :class:`BlockchainConfig`,
is used exclusively through :mod:`eth_account` and is NEVER logged,
printed or embedded in exception messages.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional
from urllib.parse import urlparse
import datetime
import requests
from pathlib import Path

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.exceptions import TimeExhausted, TransactionNotFound

try:  # web3.py >= 7
    from web3.middleware import ExtraDataToPOAMiddleware as _POA_MIDDLEWARE
except ImportError:  # web3.py 6.x
    try:
        from web3.middleware import (
            geth_poa_middleware as _POA_MIDDLEWARE,
        )
    except ImportError:  # pragma: no cover - ancient web3
        _POA_MIDDLEWARE = None

from services.blockchain.config import BlockchainConfig, load_abi

logger = logging.getLogger(__name__)

TAG = "[BLOCKCHAIN]"

VALID_CLASSIFICATIONS = frozenset({"aman", "waspada", "bahaya"})

# 25 gwei priority fee — comfortably above Amoy's floor while staying cheap.
DEFAULT_PRIORITY_FEE_WEI = 25_000_000_000


# ── typed errors --------------------------------------------------------


class BlockchainError(Exception):
    """Base class for all blockchain failures."""


class RPCUnavailableError(BlockchainError):
    """RPC endpoint unreachable / not responding."""


class InvalidPrivateKeyError(BlockchainError):
    """Private key missing or malformed."""


class InvalidContractError(BlockchainError):
    """Contract address malformed or no bytecode deployed there."""


class ChainIdMismatchError(BlockchainError):
    """RPC reports a different chain than configured."""


class InsufficientFundsError(BlockchainError):
    """Wallet balance cannot cover gas."""


class GasEstimationError(BlockchainError):
    """Node refused to estimate gas for addData."""


class TransactionFailedError(BlockchainError):
    """Transaction reverted or was rejected by the node."""


class TransactionTimeoutError(BlockchainError):
    """No receipt within the configured timeout."""


# ── helpers -------------------------------------------------------------


def build_web3(rpc_url: str, timeout_s: int) -> Web3:
    """HTTP provider with PoA extraData validation disabled.

    Polygon (Bor) is a Proof-of-Authority chain: its blocks carry an
    ``extraData`` field larger than the 32-byte geth limit, which trips
    web3's default validation middleware.  The POA middleware must be
    injected for *any* block read (head block, base fee, receipts).
    """
    w3 = Web3(Web3.HTTPProvider(
        rpc_url, request_kwargs={"timeout": timeout_s},
    ))
    if _POA_MIDDLEWARE is not None:
        w3.middleware_onion.inject(_POA_MIDDLEWARE, layer=0)
    return w3


def safe_endpoint(rpc_url: str) -> str:
    """Host-only view of an RPC URL (URLs may embed API keys)."""
    parsed = urlparse(rpc_url)
    return parsed.netloc if parsed.netloc else "<invalid-url>"


def brief_error(exc: BaseException) -> str:
    """Compact one-line description of an exception."""
    text = " ".join(str(exc).split())
    return text[:200] if text else exc.__class__.__name__


def prepare_fee_fields(w3: Web3) -> dict[str, int]:
    """Fee fields for a transaction — EIP-1559 when supported."""
    try:
        latest = w3.eth.get_block("latest")
    except Exception as exc:  # noqa: BLE001 - normalise transport errors
        raise RPCUnavailableError(
            f"cannot read head block: {brief_error(exc)}"
        ) from exc

    base_fee = latest.get("baseFeePerGas")
    if base_fee:
        max_priority = DEFAULT_PRIORITY_FEE_WEI
        return {
            "maxPriorityFeePerGas": max_priority,
            "maxFeePerGas": int(base_fee * 1.2) + max_priority,
        }
    # pre-London fallback
    return {"gasPrice": w3.eth.gas_price}


def _to_uint(value: Any, field: str) -> int:
    """Coerce a sensor value to a non-negative integer."""
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError) as exc:
        raise BlockchainError(f"{field} is not numeric: {value!r}") from exc
    if number < 0:
        raise BlockchainError(f"{field} must be >= 0, got {number}")
    return number


# ── client --------------------------------------------------------------


class PolygonAmoyClient:
    """Thin, thread-safe wrapper around web3.py for one wallet + contract."""

    def __init__(self, config: Optional[BlockchainConfig] = None) -> None:
        self._cfg = config if config is not None else BlockchainConfig.load()
        self._w3: Optional[Web3] = None
        self._account: Optional[LocalAccount] = None
        self._contract = None
        self._lock = threading.Lock()

    # -- introspection ---------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._w3 is not None

    @property
    def address(self) -> str:
        return self._account.address if self._account else ""

    def chain_id(self) -> int:
        self._require_connected()
        return self._w3.eth.chain_id  # type: ignore[union-attr]

    def get_wallet_balance_wei(self) -> int:
        """Current POL balance of the loaded wallet (wei)."""
        self._require_connected()
        return int(
            self._w3.eth.get_balance(self._account.address)  # type: ignore[union-attr]
        )

    # -- connection ------------------------------------------------------

    def connect(self) -> bool:
        """Connect to the RPC, validate wallet / chain / contract.

        Raises typed :class:`BlockchainError` subclasses on failure.
        """
        with self._lock:
            return self._connect_locked()

    def _connect_locked(self) -> bool:
        cfg = self._cfg

        if not cfg.rpc_url:
            raise RPCUnavailableError("POLYGON_AMOY_RPC_URL is not configured")
        if not cfg.private_key:
            raise InvalidPrivateKeyError(
                "POLYGON_AMOY_PRIVATE_KEY is not configured"
            )
        if not cfg.contract_address:
            raise InvalidContractError(
                "POLYGON_AMOY_CONTRACT_ADDRESS is not configured"
            )

        logger.info("%s Connecting to Polygon Amoy (%s)...",
                    TAG, safe_endpoint(cfg.rpc_url))
        w3 = build_web3(cfg.rpc_url, cfg.request_timeout_s)

        try:
            online = w3.is_connected()
        except Exception as exc:  # noqa: BLE001 - requests/urllib variety
            raise RPCUnavailableError(
                f"RPC request failed: {brief_error(exc)}"
            ) from exc
        if not online:
            raise RPCUnavailableError(
                f"RPC did not respond at {safe_endpoint(cfg.rpc_url)}"
            )

        try:
            account = Account.from_key(cfg.private_key)
        except (TypeError, ValueError) as exc:
            raise InvalidPrivateKeyError(
                "POLYGON_AMOY_PRIVATE_KEY is not a valid secp256k1 key"
            ) from exc
        self._account = account
        logger.info("%s Wallet: %s", TAG, account.address)

        try:
            reported_chain = w3.eth.chain_id
        except Exception as exc:  # noqa: BLE001
            raise RPCUnavailableError(
                f"cannot read chain ID: {brief_error(exc)}"
            ) from exc
        if reported_chain != cfg.chain_id:
            raise ChainIdMismatchError(
                f"RPC reports chain {reported_chain}, expected {cfg.chain_id}"
            )

        try:
            contract_address = Web3.to_checksum_address(cfg.contract_address)
        except (TypeError, ValueError) as exc:
            raise InvalidContractError(
                "POLYGON_AMOY_CONTRACT_ADDRESS is not a valid address"
            ) from exc

        try:
            code = w3.eth.get_code(contract_address)
        except Exception as exc:  # noqa: BLE001
            raise RPCUnavailableError(
                f"cannot fetch contract code: {brief_error(exc)}"
            ) from exc
        if len(code) == 0:
            raise InvalidContractError(
                f"no contract deployed at {contract_address} on chain "
                f"{cfg.chain_id} — deploy GasDetectionStorage first"
            )

        abi = load_abi(Path(__file__).resolve().parent / "siparta_audit_abi.json")
        self._contract = w3.eth.contract(address=contract_address, abi=abi)

        balance = self._safe_balance(w3, account.address)
        if balance == 0:
            logger.warning(
                "%s Wallet has 0 POL — transactions will fail until the "
                "address is funded from a faucet", TAG,
            )

        self._w3 = w3
        total = self._safe_total()
        logger.info(
            "%s Connected. Chain: %d | Head block: %d | Records on-chain: %s",
            TAG, reported_chain, w3.eth.block_number,
            "?" if total is None else total,
        )
        return True

    @staticmethod
    def _safe_balance(w3: Web3, address: str) -> int:
        try:
            return int(w3.eth.get_balance(address))
        except Exception:  # noqa: BLE001 - informational only
            return 0

    def _safe_total(self) -> Optional[int]:
        return None

    def _require_connected(self) -> None:
        if self._w3 is None or self._account is None:
            raise BlockchainError("client is not connected — call connect()")

    # -- write path ------------------------------------------------------

    def anchor_incident(
        self,
        incident_id: str,
        payload: dict[str, Any],
        timeout_s: Optional[int] = None,
    ) -> dict[str, Any]:
        """Upload payload to Pinata IPFS and store cid & incident_id on-chain."""
        if self._w3 is None:
            self.connect()
        self._require_connected()
        assert self._w3 is not None and self._account is not None

        # 1. Upload to Pinata IPFS
        ipfs_cid = payload.get("ipfs_cid")
        if not ipfs_cid:
            if not self._cfg.pinata_jwt:
                raise BlockchainError("PINATA_JWT is not configured")
            
            logger.info("%s Uploading metadata to Pinata IPFS...", TAG)
            headers = {
                "Authorization": f"Bearer {self._cfg.pinata_jwt}",
                "Content-Type": "application/json"
            }
            url = "https://api.pinata.cloud/pinning/pinJSONToIPFS"
            
            metadata = {
                "incident_id": incident_id,
                "classification": payload.get("classification", "unknown"),
                "sensor_data": {
                    "mics5524": payload.get("mics5524", 0),
                    "tgs2600": payload.get("tgs2600", 0),
                    "mq2": payload.get("mq2", 0),
                    "mq135": payload.get("mq135", 0),
                },
                "image_url": payload.get("image_url", ""),
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
            
            pinata_payload = {
                "pinataContent": metadata,
                "pinataMetadata": {
                    "name": f"incident-{incident_id}.json"
                }
            }
            
            try:
                resp = requests.post(url, json=pinata_payload, headers=headers, timeout=15)
                resp.raise_for_status()
                ipfs_cid = resp.json().get("IpfsHash")
            except Exception as e:
                raise BlockchainError(f"Pinata IPFS upload failed: {e}")

        # 2. Anchor to Polygon (SipartaAudit)
        try:
            incident_id_bytes = Web3.keccak(text=incident_id)
        except Exception as e:
            raise BlockchainError(f"Failed to hash incident_id: {e}")

        fn = self._w3.eth.contract(
            address=self._contract.address, abi=self._contract.abi,
        ).functions.logIncident(incident_id_bytes, ipfs_cid)

        try:
            logger.info("%s Anchoring incident to SipartaAudit...", TAG)
            tx_hash = self._sign_and_send(fn)
            logger.info("%s Transaction submitted: %s", TAG, tx_hash)

            receipt = self._wait_for_receipt(tx_hash, timeout_s)
            status = int(receipt.get("status", 0))
            if status != 1:
                raise BlockchainError(f"Transaction reverted: {tx_hash}")

            return {
                "transaction_hash": tx_hash,
                "block_number": receipt.get("blockNumber"),
                "ipfs_cid": ipfs_cid
            }
        except Exception as e:
            logger.error("%s Blockchain tx failed: %s", TAG, e)
            return {
                "transaction_hash": None,
                "block_number": 0,
                "ipfs_cid": ipfs_cid
            }

    def verify_incident(self, incident_id: str) -> bool:
        """Check if an incident exists on-chain using the verifyIncident view function."""
        if self._w3 is None:
            self.connect()
        self._require_connected()
        assert self._w3 is not None and self._contract is not None
        
        try:
            incident_id_bytes = Web3.keccak(text=incident_id)
            return self._contract.functions.verifyIncident(incident_id_bytes).call()
        except Exception as e:
            logger.error("%s Failed to verify incident %s: %s", TAG, incident_id, e)
            return False

    def _sign_and_send(self, fn: Any) -> str:
        """Estimate gas → build → sign → broadcast. Returns hex hash."""
        w3, account = self._w3, self._account
        sender = account.address

        try:
            gas = fn.estimate_gas({"from": sender})
        except ValueError as exc:
            reason = self._decode_revert(exc)
            raise GasEstimationError(
                f"gas estimation failed ({reason}) — check that this "
                f"wallet owns the contract and inputs satisfy its rules"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise GasEstimationError(
                f"gas estimation failed: {brief_error(exc)}"
            ) from exc

        try:
            nonce = w3.eth.get_transaction_count(sender, "pending")
        except Exception as exc:  # noqa: BLE001
            raise RPCUnavailableError(
                f"cannot fetch nonce: {brief_error(exc)}"
            ) from exc

        fees = prepare_fee_fields(w3)

        try:
            tx = fn.build_transaction({
                "from": sender,
                "nonce": nonce,
                "gas": int(gas),
                "chainId": self._cfg.chain_id,
                **fees,
            })
        except Exception as exc:  # noqa: BLE001
            raise TransactionFailedError(
                f"cannot build transaction: {brief_error(exc)}"
            ) from exc

        balance = self._safe_balance(w3, sender)
        price = fees.get("maxFeePerGas") or fees.get("gasPrice") or 0
        cost = int(price) * int(gas)
        if balance < cost:
            raise InsufficientFundsError(
                f"wallet {sender} holds {Web3.from_wei(balance, 'ether')} POL "
                f"but the transaction needs up to "
                f"{Web3.from_wei(cost, 'ether')} POL in gas"
            )

        signed = account.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None)
        if raw is None:  # web3.py < 1.13 attribute name
            raw = signed.rawTransaction
        try:
            sent = w3.eth.send_raw_transaction(raw)
        except ValueError as exc:
            raise TransactionFailedError(self._decode_revert(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise RPCUnavailableError(
                f"cannot broadcast transaction: {brief_error(exc)}"
            ) from exc
        return sent.hex()

    def _wait_for_receipt(
        self, tx_hash_hex: str, timeout_s: Optional[int],
    ):
        timeout = timeout_s if timeout_s else self._cfg.receipt_timeout_s
        try:
            return self._w3.eth.wait_for_transaction_receipt(
                tx_hash_hex, timeout=timeout,
            )
        except TimeExhausted as exc:
            raise TransactionTimeoutError(
                f"no receipt for {tx_hash_hex} within {timeout}s — it may "
                f"still land later; verify on PolygonScan"
            ) from exc
        except TransactionNotFound as exc:
            raise TransactionTimeoutError(
                f"transaction {tx_hash_hex} not found by the node"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise RPCUnavailableError(
                f"receipt polling failed: {brief_error(exc)}"
            ) from exc

    def _extract_record_id(self, receipt) -> Optional[int]:
        try:
            # Filter receipt logs to only our contract's logs to avoid
            # MismatchedABI warnings from system events (e.g. the Polygon
            # native-token Transfer event emitted by 0x...1010).
            contract_address = Web3.to_checksum_address(self._contract.address)
            filtered_logs = [
                log for log in receipt.get("logs", [])
                if Web3.to_checksum_address(log["address"]) == contract_address
            ]
            if not filtered_logs:
                return None
            filtered_receipt = dict(receipt)
            filtered_receipt["logs"] = filtered_logs
            events = self._contract.events.DataStored().process_receipt(
                filtered_receipt,
            )
            if events:
                return int(events[0]["args"]["id"])
        except Exception:  # noqa: BLE001 - decoding is best-effort
            pass
        return None

    @staticmethod
    def _decode_revert(exc: Exception) -> str:
        """Pull a readable message out of node error payloads."""
        data = getattr(exc, "args", ())
        if data:
            first = data[0]
            if isinstance(first, dict):
                message = first.get("message")
                if message:
                    return str(message)[:200]
        return brief_error(exc)

    # -- read path -------------------------------------------------------


