"""Independent business reference model, never mounted in a Builder workspace.

The public JSON describes business rules; this Python state machine compiles
action sequences into exact visible outcomes. It does not reuse generated JS.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal(".01")


def money(value):
    return str(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP))


def price(contract, values):
    """Aggregate identical items, apply one selected policy, round at the end."""
    rates = {p["id"]: Decimal(p["unit_price"]) for p in contract["catalogue"]}
    if values.get("manual_rate", "") != "" and contract["workflow"] == "manual_override":
        rates["A"] = Decimal(values["manual_rate"])
    quantities = {key: 0 for key in rates}
    for p, q in (
        (values["product"], values["quantity"]),
        (values["second_product"], values["second_quantity"]),
    ):
        quantities[p] += int(q)
    original = sum((rates[k] * v for k, v in quantities.items()), Decimal(0))
    rule = contract["profiles"][values["profile"]]
    kind = rule["kind"]
    discount = tax = Decimal(0)
    free = 0
    subtotal = original
    eligible = rates.get(rule.get("product"), Decimal(0)) * quantities.get(rule.get("product"), 0)
    if kind == "quantity_tiers":
        percent = max(
            (
                Decimal(t["percent"])
                for t in rule["tiers"]
                if quantities[rule["product"]] >= t["minimum"]
            ),
            default=Decimal(0),
        )
        discount = eligible * percent / 100
    elif kind == "customer_scope":
        discount = eligible * Decimal(rule["discounts"].get(values["customer"], "0")) / 100
    elif kind == "validity_dates":
        if rule["start"] <= values["date"] <= rule["end"]:
            discount = eligible * Decimal(rule["percent"]) / 100
    elif kind == "compound_discounts":
        remaining = original
        for percent in rule["percents"]:
            remaining *= 1 - Decimal(percent) / 100
        discount = original - remaining
    elif kind == "overlap_priority":
        percent = (
            rule["vip_percent"]
            if values["customer"] == "vip"
            else rule["volume_percent"]
            if quantities[rule["product"]] >= rule["volume_minimum"]
            else "0"
        )
        discount = eligible * Decimal(percent) / 100
    elif kind == "mixed_threshold":
        if sum(quantities[k] for k in rule["products"]) >= rule["minimum"]:
            discount = (
                sum((rates[k] * quantities[k] for k in rule["products"]), Decimal(0))
                * Decimal(rule["percent"])
                / 100
            )
    elif kind == "rate_override":
        if values["customer"] == rule["customer"]:
            discount = (rates[rule["product"]] - Decimal(rule["rate"])) * quantities[
                rule["product"]
            ]
    elif kind == "tax_inclusive":
        subtotal = Decimal(money(original / (1 + Decimal(rule["tax_percent"]) / 100)))
        tax = original - subtotal
    elif kind == "net_total_discount":
        discount = min(original, Decimal(rule["amount"]))
        tax = Decimal(money((original - discount) * Decimal(rule["tax_percent"]) / 100))
    elif kind == "free_items":
        free = quantities[rule["product"]] // rule["buy"] * rule["free"]
    else:
        raise ValueError(kind)
    freight = Decimal(contract.get("shipping", {}).get(values.get("shipping", "pickup"), "0"))
    return dict(
        subtotal=money(subtotal),
        discount=money(discount),
        tax=money(tax),
        total=money(subtotal - discount + tax + freight),
        free_quantity=str(free),
        freight=money(freight),
    )


DEFAULTS = dict(
    profile="quantity_tiers",
    product="A",
    quantity="1",
    second_product="B",
    second_quantity="0",
    customer="standard",
    date="2026-03-15",
    manual_rate="",
    shipping="pickup",
)


class QuoteModel:
    def __init__(self, contract):
        self.contract = contract
        self.records = {
            k: dict(
                values=deepcopy(DEFAULTS),
                state="Draft",
                revision=0,
                approved_revision=-1,
                history_count=0,
                approvers=[],
            )
            for k in ("Q1", "Q2")
        }
        self.record = "Q1"
        self.role = "seller"
        self.actor = "seller1"
        self.reason = ""
        self.today = "2026-03-15"

    @property
    def current(self):
        return self.records[self.record]

    def snapshot(self):
        r = self.current
        return dict(
            **price(self.contract, r["values"]),
            state=r["state"],
            revision=str(r["revision"]),
            approved_revision=str(r["approved_revision"]),
            history_count=str(r["history_count"]),
        )

    def apply(self, op):
        for key in ("record", "role", "actor", "reason", "today"):
            if key in op:
                setattr(self, key, op[key])
        r = self.current
        state = r["state"]
        action = op.get("action")
        if action == "reload":
            self.record = "Q1"
            self.role = "seller"
            self.actor = "seller1"
            self.reason = ""
            self.today = "2026-03-15"
            return False
        if action is None:
            return False
        if action == "calculate":
            values = dict(r["values"], **op.get("values", {}))
            try:
                valid = all(
                    Decimal(values[k]) == int(Decimal(values[k]))
                    and int(Decimal(values[k])) >= minimum
                    for k, minimum in (("quantity", 1), ("second_quantity", 0))
                )
                valid = valid and (
                    values["manual_rate"] == "" or Decimal(values["manual_rate"]) > 0
                )
            except (ValueError, ArithmeticError):
                valid = False
            if not valid or self.role != "seller" or state in ("Accepted", "Cancelled"):
                return False
            if values != r["values"]:
                r.update(
                    values=values,
                    revision=r["revision"] + 1,
                    state="Draft",
                    approved_revision=-1,
                    approvers=[],
                )
                r["history_count"] += 1
            return True
        if action == "submit" and self.role == "seller" and state in ("Draft", "Rejected"):
            r.update(state="PendingManager", approvers=[], approved_revision=-1)
        elif action == "approve" and self.role == "manager" and state == "PendingManager":
            if self.actor in r["approvers"]:
                return False
            r["approvers"].append(self.actor)
            if self.contract["workflow"] == "dual_manager" and len(r["approvers"]) < 2:
                pass
            elif self.contract["workflow"] == "two_stage" or (
                self.contract["workflow"] == "threshold"
                and Decimal(self.snapshot()["total"])
                >= Decimal(self.contract["approval_threshold"])
            ):
                r["state"] = "PendingFinance"
            else:
                r.update(state="Approved", approved_revision=r["revision"])
        elif action == "approve" and self.role == "finance" and state == "PendingFinance":
            r.update(state="Approved", approved_revision=r["revision"])
        elif action == "reject" and (
            (self.role == "manager" and state == "PendingManager")
            or (self.role == "finance" and state == "PendingFinance")
        ):
            if self.contract["workflow"] == "rejection_reason" and not self.reason.strip():
                return False
            r.update(state="Rejected", approvers=[], approved_revision=-1)
        elif action == "accept" and self.role == "customer" and state == "Approved":
            if self.contract["workflow"] == "customer_owner" and self.actor != "client1":
                return False
            if self.contract["workflow"] == "expiry" and self.today > self.contract["valid_until"]:
                return False
            r["state"] = "Accepted"
        elif (
            action == "cancel" and self.role == "seller" and state not in ("Accepted", "Cancelled")
        ):
            r.update(state="Cancelled", approved_revision=-1, approvers=[])
        elif (
            action == "amend"
            and self.role == "seller"
            and state == "Cancelled"
            and self.contract["workflow"] == "cancel_amend"
        ):
            r.update(state="Draft", revision=r["revision"] + 1, approved_revision=-1, approvers=[])
        else:
            return False
        r["history_count"] += 1
        return True


def approve_steps(contract):
    ops = [dict(role="manager", actor="manager1", action="approve")]
    if contract["workflow"] == "dual_manager":
        ops += [dict(action="approve"), dict(actor="manager2", action="approve")]
    if contract["workflow"] in ("threshold", "two_stage"):
        ops += [dict(role="finance", actor="finance1", action="approve")]
    return ops


def journeys(contract, profile, *, private=False):
    """Different public/held-out values and action orders, same declared rules."""
    # Pure price boundaries and wrong-role preservation are part of every combo.
    q = "11" if private else "10"
    vector = dict(
        profile=profile,
        quantity=q,
        second_product="A" if private else "B",
        second_quantity="2",
        customer="vip",
        date="2026-03-31" if private else "2026-03-15",
    )
    prepare = dict(role="seller", actor="seller1", action="calculate", values=vector)
    normal = [
        prepare,
        dict(action="submit"),
        dict(role="customer", actor="client1", action="accept"),
        *approve_steps(contract),
        dict(role="customer", actor="client1", action="accept"),
        dict(role="seller", action="calculate", values={"quantity": "3"}),
    ]
    edit = [
        prepare,
        dict(action="submit"),
        *approve_steps(contract),
        dict(role="seller", actor="seller1", action="calculate", values={"quantity": "4"}),
        dict(role="customer", actor="client1", action="accept"),
        dict(role="seller", action="submit"),
        *approve_steps(contract),
    ]
    invalid = [
        prepare,
        dict(action="calculate", values={"quantity": "1.5" if private else "0"}),
        dict(action="calculate", values={"quantity": q}),
        dict(role="customer", actor="intruder", action="calculate", values={"quantity": "2"}),
        dict(role="seller", action="submit"),
        dict(role="finance", action="approve"),
    ]
    specialized = [prepare]
    kind = contract["workflow"]
    if kind == "rejection_reason":
        specialized += [
            dict(action="submit"),
            dict(role="manager", actor="manager1", reason="", action="reject"),
            dict(reason="Price needs review", action="reject"),
            dict(role="seller", action="calculate", values={"quantity": "2"}),
            dict(action="submit"),
            *approve_steps(contract),
        ]
    elif kind == "cancel_amend":
        specialized += [
            dict(action="submit"),
            *approve_steps(contract),
            dict(role="seller", action="cancel"),
            dict(role="customer", action="accept"),
            dict(role="seller", action="amend"),
            dict(action="submit"),
            *approve_steps(contract),
        ]
    elif kind == "customer_owner":
        specialized += [
            dict(action="submit"),
            *approve_steps(contract),
            dict(role="customer", actor="intruder", action="accept"),
            dict(actor="client1", action="accept"),
        ]
    elif kind == "expiry":
        specialized += [
            dict(action="submit"),
            *approve_steps(contract),
            dict(role="customer", actor="client1", today="2026-04-01", action="accept"),
            dict(today=contract["valid_until"], action="accept"),
        ]
    elif kind == "record_persistence":
        specialized += [
            dict(action="submit"),
            *approve_steps(contract),
            dict(
                record="Q2",
                role="seller",
                action="calculate",
                values={"profile": profile, "quantity": "3"},
            ),
            dict(action="submit"),
            dict(action="reload"),
            dict(record="Q1"),
            dict(role="customer", actor="client1", action="accept"),
            dict(record="Q2"),
        ]
    elif kind == "manual_override":
        specialized += [
            dict(action="calculate", values={"manual_rate": "75.55" if private else "80"}),
            dict(action="calculate"),
            dict(action="submit"),
            *approve_steps(contract),
            dict(role="seller", action="calculate", values={"second_quantity": "1"}),
            dict(action="calculate"),
        ]
    elif kind == "threshold":
        specialized += [
            dict(
                action="calculate",
                values={"quantity": "1", "second_quantity": "0", "customer": "standard"},
            ),
            dict(action="submit"),
            *approve_steps(contract),
            dict(role="seller", action="calculate", values={"quantity": "20"}),
            dict(action="submit"),
            *approve_steps(contract),
        ]
    elif kind == "dual_manager":
        specialized += [
            dict(action="submit"),
            *approve_steps(contract),
            dict(role="customer", actor="client1", action="accept"),
        ]
    else:
        specialized += [
            dict(action="submit"),
            dict(role="manager", actor="manager1", reason="Needs correction", action="reject"),
            dict(role="seller", action="submit"),
            *approve_steps(contract),
        ]
    # Every policy also gets applicable/inapplicable boundaries, independently
    # of the workflow. The normal VIP path alone would miss partner-only rates
    # and dates outside a promotion's interval.
    kind = contract["profiles"][profile]["kind"]
    edge_values = {
        "quantity_tiers": [{"quantity": q} for q in ("4", "5", "9", "10")],
        "customer_scope": [
            {"customer": c, "quantity": "6"} for c in ("partner", "standard", "vip")
        ],
        "validity_dates": [
            {"date": d} for d in ("2026-02-28", "2026-03-01", "2026-03-31", "2026-04-01")
        ],
        "compound_discounts": [
            dict(product="C", quantity="3", second_product="B", second_quantity="5"),
            dict(quantity="1", second_quantity="0"),
        ],
        "overlap_priority": [
            dict(customer="standard", quantity="10"),
            dict(customer="vip", quantity="10"),
            dict(customer="partner", quantity="3"),
        ],
        "mixed_threshold": [
            dict(product="A", quantity="3", second_product="B", second_quantity="2"),
            dict(quantity="2", second_quantity="2"),
            dict(product="C", quantity="10", second_quantity="0"),
        ],
        "rate_override": [
            dict(customer="partner", quantity="2"),
            dict(customer="vip", quantity="2"),
            dict(customer="partner", product="B", quantity="3", second_quantity="0"),
        ],
        "tax_inclusive": [
            dict(product="C", quantity="1", second_product="B", second_quantity="1"),
            dict(product="B", quantity="1", second_quantity="0"),
        ],
        "net_total_discount": [
            dict(product="B", quantity="1", second_quantity="0"),
            dict(product="A", quantity="1", second_quantity="0"),
        ],
        "free_items": [
            dict(quantity=str(max(1, contract["profiles"][profile].get("buy", 1) + offset)))
            for offset in (-1, 0, 1)
        ],
    }[kind]
    if private:
        edge_values = list(reversed(edge_values))
    edges = [dict(action="calculate", values=dict(profile=profile, **v)) for v in edge_values] + [
        dict(action="calculate")
    ]
    isolation = [
        prepare,
        dict(action="submit"),
        *approve_steps(contract),
        dict(
            record="Q2",
            role="seller",
            action="calculate",
            values={"profile": profile, "quantity": "7" if private else "3"},
        ),
        dict(role="manager", action="approve"),
        dict(record="Q1"),
        dict(role="customer", actor="client1", action="accept"),
        dict(record="Q2"),
    ]
    result = [
        ("normal", normal),
        ("edit_regression", edit),
        ("invalid_recovery", invalid),
        ("workflow_specific", specialized),
        ("pricing_boundaries", edges),
        ("record_isolation", isolation),
    ]
    if contract.get("version", 1) >= 2:
        shipping = [
            prepare,
            dict(action="calculate", values={"shipping": "express" if private else "standard"}),
            dict(action="calculate"),
            dict(action="submit"),
            *approve_steps(contract),
            dict(role="seller", action="calculate", values={"shipping": "pickup"}),
            dict(role="customer", actor="client1", action="accept"),
            dict(role="seller", action="submit"),
            *approve_steps(contract),
        ]
        result.append(("new_shipping", shipping))
    return result


def compile_acceptance(contract, *, private=False):
    """Persist inspectable per-step acceptance, without requiring model prose."""
    result = []
    for profile in contract["profiles"]:
        for name, ops in journeys(contract, profile, private=private):
            model = QuoteModel(contract)
            steps = []
            for op in ops:
                accepted = model.apply(op)
                steps.append(
                    dict(operation=op, accepted=accepted, expected_visible=model.snapshot())
                )
            result.append(dict(profile=profile, journey=name, steps=steps))
    return dict(
        app_id=contract["id"], version=contract["version"], private=private, journeys=result
    )
