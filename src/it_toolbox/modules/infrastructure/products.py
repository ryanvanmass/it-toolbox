"""The Infrastructure module's products, in tree-root order.

Each entry is an InfrastructureProduct subclass (see product.py). Planned
roots: TrueNAS, Proxmox, PBS -- each lands with its own PR -- with GL.iNet
last.
"""

from it_toolbox.modules.infrastructure.glinet import GlinetProduct
from it_toolbox.modules.infrastructure.product import InfrastructureProduct

PRODUCT_CLASSES: list[type[InfrastructureProduct]] = [GlinetProduct]
