"""Bigtable MCP Toolset and Analytical Connectors for Cymbal Operations Agent.

Queries Cloud Bigtable instance 'operations-db' via deployed MCP Toolbox microservice on Cloud Run,
Bigtable GoogleSQL query executor, and direct SDK row set fallback.
"""

import base64
import json
import logging
import os
import struct
import subprocess
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from google.adk.tools import FunctionTool
from google.cloud import bigtable
from google.cloud.bigtable.data import BigtableDataClient
from google.cloud.bigtable.row_set import RowSet

from app.app_utils.pii import mask_card_pii, mask_data_structures

load_dotenv()

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", os.getenv("GOOGLE_CLOUD_PROJECT", "project-elevate-503005"))
BIGTABLE_INSTANCE_ID = os.getenv("BIGTABLE_INSTANCE_ID", "operations-db")
BIGTABLE_TABLE_ID = os.getenv("BIGTABLE_TABLE_ID", "cashier_realtime_alerts")
BIGTABLE_ENRICHED_TABLE_ID = os.getenv("BIGTABLE_ENRICHED_TABLE_ID", "pos_transactions_enriched")
BIGTABLE_MCP_URL = os.getenv("BIGTABLE_MCP_URL", "https://mcp-toolbox-bigtable-519629786311.us-central1.run.app")
SERVICE_ACCOUNT = os.getenv(
    "SERVICE_ACCOUNT",
    f"cymbal-sa-data@{PROJECT_ID}.iam.gserviceaccount.com" if PROJECT_ID else "",
)

_bigtable_client: Optional[bigtable.Client] = None


def _get_bigtable_table(table_name: str = BIGTABLE_TABLE_ID):
    global _bigtable_client
    if _bigtable_client is None:
        _bigtable_client = bigtable.Client(project=PROJECT_ID)
    instance = _bigtable_client.instance(BIGTABLE_INSTANCE_ID)
    return instance.table(table_name)


def _decode_metric_bytes(col_name: str, raw_bytes: bytes) -> Any:
    """Decodes binary encoded fields from Bigtable."""
    if not raw_bytes:
        return None
    if col_name in ("audit_status", "last_event_ts"):
        return raw_bytes.decode("utf-8", errors="replace")
    if len(raw_bytes) == 8:
        if col_name in (
            "cashier_1h_txn_count",
            "cashier_1h_manual_override_count",
            "cashier_1h_promo_count",
        ):
            return struct.unpack(">q", raw_bytes)[0]
        if col_name in (
            "cashier_1h_avg_discount_pct",
            "cashier_1h_promo_rate",
            "cashier_1h_total_discount_usd",
            "risk_score",
        ):
            return round(struct.unpack(">d", raw_bytes)[0], 4)
    try:
        val_str = raw_bytes.decode("utf-8")
        if val_str.startswith('"') and val_str.endswith('"'):
            val_str = json.loads(val_str)
        return val_str
    except Exception:
        return str(raw_bytes)


def _query_bigtable_direct(prefix: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Direct fallback query using Bigtable SDK with row set prefix scanning."""
    table = _get_bigtable_table(BIGTABLE_TABLE_ID)
    row_set = RowSet()
    row_set.add_row_range_with_prefix(prefix)
    rows = table.read_rows(row_set=row_set, limit=limit)
    results = []
    for row in rows:
        row_dict: Dict[str, Any] = {"row_key": row.row_key.decode("utf-8")}
        for fam, cols in row.cells.items():
            for col, cells in cols.items():
                col_name = col.decode("utf-8")
                val = cells[0].value
                row_dict[col_name] = _decode_metric_bytes(col_name, val)
        results.append(row_dict)
    return results


def _get_oidc_token(audience: str) -> Optional[str]:
    """Generates GCP OIDC identity token for target audience."""
    try:
        cmd = ["gcloud", "auth", "print-identity-token"]
        if SERVICE_ACCOUNT:
            cmd.append(f"--impersonate-service-account={SERVICE_ACCOUNT}")
        cmd.append(f"--audiences={audience}")
        token = subprocess.check_output(
            cmd,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        ).strip().splitlines()[-1]
        return token
    except Exception as e:
        logger.warning(f"Failed to get impersonated token, falling back to direct token: {e}")
        try:
            return subprocess.check_output(
                ["gcloud", "auth", "print-identity-token"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=10,
            ).strip().splitlines()[-1]
        except Exception:
            return None


def _query_mcp_service(prefix: str) -> List[Dict[str, Any]]:
    """Calls Cloud Run MCP Toolbox microservice over HTTP JSON-RPC."""
    import urllib.request

    target_url = BIGTABLE_MCP_URL.rstrip("/")
    mcp_endpoint = f"{target_url}/mcp"
    token = _get_oidc_token(target_url)

    headers = {
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_cashier_realtime_alerts",
            "arguments": {"prefix": f"{prefix}%"},
        },
    }

    req = urllib.request.Request(
        mcp_endpoint,
        data=json.dumps(req_payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        if body.get("result", {}).get("isError"):
            raise RuntimeError(f"MCP error: {body['result']}")

        content = body.get("result", {}).get("content", [])
        decoded_rows = []
        for item in content:
            if item.get("type") == "text":
                row_raw = json.loads(item["text"])
                row_decoded: Dict[str, Any] = {"row_key": row_raw.get("row_key")}
                for k, v in row_raw.items():
                    if k == "row_key":
                        continue
                    if isinstance(v, str):
                        try:
                            raw_b = base64.b64decode(v)
                            row_decoded[k] = _decode_metric_bytes(k, raw_b)
                        except Exception:
                            row_decoded[k] = v
                    else:
                        row_decoded[k] = v
                decoded_rows.append(row_decoded)
        return decoded_rows


def query_cashier_realtime_alerts(
    store_id: str, cashier_id: str
) -> str:
    """Reads live 1-hour rolling metrics and audit status flags for a cashier from Cloud Bigtable.

    Args:
        store_id: The store identifier, e.g. 'STORE_048' or '48' or '048'.
        cashier_id: The cashier identifier, e.g. 'CASH_1190' or '1190'.

    Returns:
        JSON string containing the latest 1-hour rolling metrics (transaction count, manual override count,
        promo count, promo rate, average discount percentage, total discount USD, risk score, and audit status).
    """
    clean_store = store_id.strip().upper()
    if clean_store.startswith("STORE_"):
        clean_store = clean_store.replace("STORE_", "")
    clean_store = clean_store.zfill(3)
    norm_store = f"STORE_{clean_store}"

    clean_cashier = cashier_id.strip().upper()
    if not clean_cashier.startswith("CASH_"):
        clean_cashier = f"CASH_{clean_cashier}"

    row_key_prefix = f"{norm_store}#{clean_cashier}"

    try:
        try:
            rows = _query_mcp_service(row_key_prefix)
            if not rows:
                rows = _query_bigtable_direct(row_key_prefix)
        except Exception as mcp_err:
            logger.warning(f"MCP service call failed ({mcp_err}), falling back to direct Bigtable query.")
            rows = _query_bigtable_direct(row_key_prefix)

        if not rows:
            return json.dumps({
                "status": "NOT_FOUND",
                "message": f"No real-time alerts or telemetry found for {norm_store}, Cashier {clean_cashier}.",
                "row_key_prefix": row_key_prefix,
            })

        latest_record = rows[0]
        result_payload = {
            "status": "SUCCESS",
            "store_id": norm_store,
            "cashier_id": clean_cashier,
            "latest_event_ts": latest_record.get("last_event_ts"),
            "audit_status": latest_record.get("audit_status"),
            "metrics_1h": {
                "txn_count": latest_record.get("cashier_1h_txn_count"),
                "manual_override_count": latest_record.get("cashier_1h_manual_override_count"),
                "promo_count": latest_record.get("cashier_1h_promo_count"),
                "promo_rate": latest_record.get("cashier_1h_promo_rate"),
                "avg_discount_pct": latest_record.get("cashier_1h_avg_discount_pct"),
                "total_discount_usd": latest_record.get("cashier_1h_total_discount_usd"),
                "risk_score": latest_record.get("risk_score"),
            },
            "history_rows_scanned": len(rows),
        }
        return json.dumps(mask_data_structures(result_payload), indent=2)

    except Exception as e:
        logger.error(f"Error querying Bigtable cashier alerts: {e}", exc_info=True)
        return json.dumps({
            "status": "ERROR",
            "message": f"Failed to retrieve real-time alerts for Cashier {clean_cashier} at {norm_store}: {str(e)}",
        })


def read_pos_transactions_enriched_sql(
    store_id: str,
    transaction_id: str = "",
    limit: int = 5,
) -> str:
    """Queries enriched point-of-sale transactions from Cloud Bigtable 'pos_transactions_enriched' table using GoogleSQL.

    Use this analytical sub-tool to inspect:
    - Enriched line-item details, card brands, POS terminal IDs, totals, and discounts.
    - Transaction breakdown for a specific store or transaction ID in Cloud Bigtable.
    - PII-masked payment methods and audit details.

    Args:
        store_id: Store identifier, e.g. 'STORE_048' or '48' or 'STORE_001'.
        transaction_id: Optional specific transaction ID, e.g. 'TXN-20260910-0000715'.
        limit: Maximum number of enriched transactions to return (default: 5, max: 20).

    Returns:
        JSON string containing list of enriched transaction records with payment PII masked.
    """
    clean_store = store_id.strip().upper()
    if clean_store.startswith("STORE_"):
        clean_store = clean_store.replace("STORE_", "")
    clean_store = clean_store.zfill(3)
    norm_store = f"STORE_{clean_store}"

    clamped_limit = max(1, min(limit, 20))
    clean_tx = transaction_id.strip().upper()

    if clean_tx:
        exact_row_key = f"{norm_store}#{clean_tx}"
        sql_query = f"""
        SELECT _key, tx
        FROM {BIGTABLE_ENRICHED_TABLE_ID}
        WHERE _key = b'{exact_row_key}'
        LIMIT {clamped_limit}
        """
    else:
        prefix_start = f"{norm_store}#"
        prefix_end = f"{norm_store}$\uffff"
        sql_query = f"""
        SELECT _key, tx
        FROM {BIGTABLE_ENRICHED_TABLE_ID}
        WHERE _key >= b'{prefix_start}' AND _key < b'{prefix_end}'
        LIMIT {clamped_limit}
        """

    records: List[Dict[str, Any]] = []

    # Attempt 1: Bigtable Data Client with GoogleSQL execute_query
    try:
        with BigtableDataClient(project=PROJECT_ID) as client:
            res = client.execute_query(
                instance_id=BIGTABLE_INSTANCE_ID,
                app_profile_id="default",
                query=sql_query,
            )
            for row in res:
                row_fields = dict(row._fields)
                raw_key = row_fields.get("_key", b"")
                row_key_str = raw_key.decode("utf-8", errors="replace") if isinstance(raw_key, bytes) else str(raw_key)

                tx_map = row_fields.get("tx", {})
                record: Dict[str, Any] = {"row_key": row_key_str}
                if isinstance(tx_map, dict):
                    for col_b, val_b in tx_map.items():
                        col_name = col_b.decode("utf-8") if isinstance(col_b, bytes) else str(col_b)
                        val_str = val_b.decode("utf-8", errors="replace") if isinstance(val_b, bytes) else str(val_b)
                        try:
                            if (val_str.startswith("{") and val_str.endswith("}")) or (val_str.startswith("[") and val_str.endswith("]")):
                                record[col_name] = json.loads(val_str)
                            elif val_str.startswith('"') and val_str.endswith('"'):
                                record[col_name] = json.loads(val_str)
                            else:
                                record[col_name] = val_str
                        except Exception:
                            record[col_name] = val_str
                records.append(record)
    except Exception as sql_err:
        logger.warning(f"Bigtable execute_query SQL failed ({sql_err}), falling back to direct SDK prefix scan.")
        try:
            table = _get_bigtable_table(BIGTABLE_ENRICHED_TABLE_ID)
            row_set = RowSet()
            if clean_tx:
                row_set.add_row_key(f"{norm_store}#{clean_tx}".encode("utf-8"))
            else:
                row_set.add_row_range_with_prefix(f"{norm_store}#".encode("utf-8"))
            rows = table.read_rows(row_set=row_set, limit=clamped_limit)
            for row in rows:
                record = {"row_key": row.row_key.decode("utf-8", errors="replace")}
                for fam, cols in row.cells.items():
                    for col, cells in cols.items():
                        col_name = col.decode("utf-8")
                        raw_val = cells[0].value
                        record[col_name] = _decode_metric_bytes(col_name, raw_val)
                records.append(record)
        except Exception as direct_err:
            logger.error(f"Direct Bigtable fallback also failed: {direct_err}", exc_info=True)
            return json.dumps({
                "status": "ERROR",
                "message": f"Failed to retrieve enriched transactions from Bigtable: {str(direct_err)}",
            })

    if not records:
        return json.dumps({
            "status": "NOT_FOUND",
            "message": f"No enriched transactions found for {norm_store} (query: {clean_tx or 'ALL'}).",
            "store_id": norm_store,
        })

    result_payload = {
        "status": "SUCCESS",
        "store_id": norm_store,
        "records_count": len(records),
        "transactions": records,
    }
    return json.dumps(mask_data_structures(result_payload), indent=2)


bigtable_realtime_alerts_tool = FunctionTool(query_cashier_realtime_alerts)
bigtable_enriched_sql_tool = FunctionTool(read_pos_transactions_enriched_sql)
bigtable_mcp_toolset = bigtable_realtime_alerts_tool
