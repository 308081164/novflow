"""NovFlow offline Ed25519 licensing (shared by desktop + Image Engine DLC)."""

from .products import DESKTOP, IMAGE_DLC, ProductProfile
from .license_service import LicenseService

__all__ = ["DESKTOP", "IMAGE_DLC", "ProductProfile", "LicenseService"]
