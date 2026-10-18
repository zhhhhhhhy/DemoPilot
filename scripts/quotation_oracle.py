"""Independent Decimal reference implementation for quotation business audit.

This file and the rule configurations are evaluator-only. They are never
included in the Builder's mounted fixtures or its engineering repair feedback.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
CENT = Decimal("0.01")


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def expected_quote(spec, vector):
    prices = {item["id"]: Decimal(item["unit_price"]) for item in spec["catalogue"]}
    quantities = {}
    for product, quantity in ((vector["product"], vector["quantity"]),
                              (vector["second_product"], vector["second_quantity"])):
        quantities[product] = quantities.get(product, 0) + int(quantity)
    original = sum((prices[product] * qty for product, qty in quantities.items()), ZERO)
    config = spec["rule_config"]
    kind = config["kind"]
    discount, tax, free = ZERO, ZERO, 0
    subtotal = original

    if kind == "quantity_tiers":
        product = config["product"]
        qty = quantities.get(product, 0)
        percent = ZERO
        for tier in sorted(config["tiers"], key=lambda t: t["minimum"]):
            if qty >= tier["minimum"]:
                percent = Decimal(tier["percent"])
        discount = prices[product] * qty * percent / HUNDRED
    elif kind == "customer_scope":
        product = config["product"]
        percent = Decimal(config["discounts"].get(vector["customer"], "0"))
        discount = prices[product] * quantities.get(product, 0) * percent / HUNDRED
    elif kind == "validity_dates":
        if config["start"] <= vector["date"] <= config["end"]:
            product = config["product"]
            discount = prices[product] * quantities.get(product, 0) * Decimal(config["percent"]) / HUNDRED
    elif kind == "compound_discounts":
        remaining = original
        for percent in config["percents"]:
            remaining *= ONE - Decimal(percent) / HUNDRED
        discount = original - remaining
    elif kind == "overlap_priority":
        product = config["product"]
        qty = quantities.get(product, 0)
        if vector["customer"] == "vip":
            percent = Decimal(config["vip_percent"])
        elif qty >= config["volume_minimum"]:
            percent = Decimal(config["volume_percent"])
        else:
            percent = ZERO
        discount = prices[product] * qty * percent / HUNDRED
    elif kind == "mixed_threshold":
        qty = sum(quantities.get(product, 0) for product in config["products"])
        if qty >= config["minimum"]:
            eligible = sum((prices[product] * quantities.get(product, 0) for product in config["products"]), ZERO)
            discount = eligible * Decimal(config["percent"]) / HUNDRED
    elif kind == "rate_override":
        if vector["customer"] == config["customer"]:
            product = config["product"]
            discount = (prices[product] - Decimal(config["rate"])) * quantities.get(product, 0)
    elif kind == "tax_inclusive":
        subtotal = money(original / (ONE + Decimal(config["tax_percent"]) / HUNDRED))
        tax = original - subtotal
    elif kind == "net_total_discount":
        discount = min(original, Decimal(config["amount"]))
        tax = money((original - discount) * Decimal(config["tax_percent"]) / HUNDRED)
    elif kind == "free_items":
        free = quantities.get(config["product"], 0) // config["buy"] * config["free"]
    else:
        raise ValueError(f"Unknown rule family: {kind}")

    total = subtotal - discount + tax
    return dict(subtotal=str(money(subtotal)), discount=str(money(discount)),
                tax=str(money(tax)), total=str(money(total)), free_quantity=free)
