"""Turn each source into document rows with the same columns.

Output columns: doc_id, doc_type, title, text, vin, unit_no, model, system_category,
                dtc_codes, doc_date, source_ref
"""


def work_order_documents(work_orders_df):
    """Work orders (Spark DataFrame) -> documents. One per work order."""
    # TODO
    raise NotImplementedError


def sop_documents(sop_folder: str):
    """Markdown SOP files -> list of document dicts. One per file."""
    # TODO
    raise NotImplementedError


def dtc_guide_documents(spn_ref_df, fmi_ref_df, dtc_events_df):
    """SPN/FMI reference tables -> one guide document per SPN."""
    # TODO
    raise NotImplementedError
