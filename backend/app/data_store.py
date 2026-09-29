"""Read-only access to the synthetic AP dataset.

Everything goes through `DataStore`, so swapping JSON files for PostgreSQL later
means reimplementing this class only.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class DataStore:
    def __init__(self, data_dir: Path = DATA_DIR):
        def load(name: str):
            return json.loads((data_dir / name).read_text(encoding="utf-8"))

        self.company: dict = load("company.json")
        self.vendors: dict[str, dict] = {v["id"]: v for v in load("vendors.json")}
        self.purchase_orders: dict[str, dict] = {p["id"]: p for p in load("purchase_orders.json")}
        self.goods_receipts: dict[str, dict] = {g["id"]: g for g in load("goods_receipts.json")}
        self.invoices: dict[str, dict] = {i["id"]: i for i in load("invoices.json")}
        self.payment_terms: dict[str, dict] = {t["code"]: t for t in load("payment_terms.json")}
        self.approval_rules: dict = load("approval_rules.json")
        self.historical_cases: list[dict] = load("historical_cases.json")
        self.team_notes: list[dict] = load("team_notes.json")

    def get_vendor(self, vendor_id: str) -> dict | None:
        return self.vendors.get(vendor_id)

    def get_invoice(self, invoice_id: str) -> dict | None:
        return self.invoices.get(invoice_id)

    def get_purchase_order(self, po_id: str | None) -> dict | None:
        return self.purchase_orders.get(po_id) if po_id else None

    def get_goods_receipt(self, grn_id: str | None) -> dict | None:
        return self.goods_receipts.get(grn_id) if grn_id else None

    def pending_invoices(self) -> list[dict]:
        return [i for i in self.invoices.values() if i["status"] == "pending"]

    def replay_invoices(self) -> list[dict]:
        return sorted((i for i in self.invoices.values() if i["status"] == "replay"),
                      key=lambda i: i["replay"]["arrived_on"])

    def paid_invoices_for_vendor(self, vendor_id: str) -> list[dict]:
        return sorted(
            (i for i in self.invoices.values() if i["vendor_id"] == vendor_id and i["status"] == "paid"),
            key=lambda i: i["invoice_date"],
        )

    def paid_invoices_for_po(self, po_id: str) -> list[dict]:
        return [i for i in self.invoices.values() if i["po_id"] == po_id and i["status"] == "paid"]


@lru_cache(maxsize=1)
def get_store() -> DataStore:
    return DataStore()
