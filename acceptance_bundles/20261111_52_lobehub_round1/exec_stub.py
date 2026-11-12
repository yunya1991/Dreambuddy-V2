def execute(card):
    """验收用桩执行器：只回显，不触发任何真实交易。"""
    return {"ok": True, "stub": True, "card_id": (card or {}).get("id")}
