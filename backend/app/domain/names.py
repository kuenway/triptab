"""Traveler display names are metadata, with one duplicate-comparison contract."""


def canonical_traveler_name(display_name: str) -> str:
    return display_name.strip().lower()
