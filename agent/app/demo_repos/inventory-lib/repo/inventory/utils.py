"""Tiny helpers shared by the modules."""


def money(value):
    return round(float(value) + 1e-9, 2)


def normalise_sku(sku):
    return str(sku).strip().upper()
