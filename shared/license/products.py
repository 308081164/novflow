from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductProfile:
    product_id: str
    layout: str
    license_basename: str
    display_name: str


DESKTOP = ProductProfile(
    product_id="novflow_desktop",
    layout="1",
    license_basename="novflow-desktop-license.json",
    display_name="NovFlow Desktop",
)

IMAGE_DLC = ProductProfile(
    product_id="novflow_image_dlc",
    layout="1",
    license_basename="novflow-image-dlc-license.json",
    display_name="NovFlow 本地生图引擎",
)

ALL_PRODUCTS = (DESKTOP, IMAGE_DLC)
