"""
Gate 3 - Other-Site Stock Check
Scans balances of the matched SKU across company warehouses/nodes and
drafts an internal transfer recommendation when matching idle/excess
stock exists elsewhere in the network.
"""


def check_other_sites(sku: str, requested_qty: int, stock_df, requesting_site_keyword="Requesting Site"):
    """
    Only idle/excess stock at other sites is eligible for an internal
    transfer. Stock marked "active" elsewhere is still in productive use
    at that site and is left alone — only genuinely idle/excess/
    project-canceled balances are candidates for reallocation.
    """
    if sku is None:
        return {
            "sku": sku,
            "other_sites": [],
            "transferable_qty": 0,
            "remaining_after_transfer": requested_qty,
            "status": "not_applicable",
        }

    matches = stock_df[stock_df["sku"] == sku]
    other_sites = matches[~matches["warehouse"].str.contains(requesting_site_keyword, na=False)]
    idle_sites = other_sites[
        other_sites["status"].str.contains("excess|idle", case=False, na=False, regex=True)
    ]

    other_sites_list = []
    transferable_qty = 0
    for _, row in idle_sites.iterrows():
        qty = int(row["quantity"])
        if qty <= 0:
            continue
        other_sites_list.append({
            "warehouse": row["warehouse"],
            "quantity": qty,
            "stock_status": row["status"],
        })
        transferable_qty += qty

    transfer_amount = min(transferable_qty, requested_qty)
    remaining_after_transfer = max(requested_qty - transfer_amount, 0)

    status = "transfer_available" if transfer_amount > 0 else "no_other_stock"

    return {
        "sku": sku,
        "other_sites": other_sites_list,
        "transferable_qty": transfer_amount,
        "remaining_after_transfer": remaining_after_transfer,
        "status": status,
    }
