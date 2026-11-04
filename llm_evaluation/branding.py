"""Branding for the PDF / Excel (same look as complify-chat). Override with BRAND_NAME / BRAND_COLOR in .env."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Branding:
    brand_name: str
    brand_color: str


def get_settings() -> Branding:
    return Branding(brand_name=os.environ.get("BRAND_NAME", "Complify"),
                    brand_color=os.environ.get("BRAND_COLOR", "#086457"))