"""The Infrastructure module's products, in tree-root order.

Each entry is an InfrastructureProduct subclass (see product.py). Planned
roots: TrueNAS, Proxmox, PBS -- each lands with its own PR.
"""

from it_toolbox.modules.infrastructure.product import InfrastructureProduct
from it_toolbox.modules.infrastructure.proxmox import ProxmoxProduct

PRODUCT_CLASSES: list[type[InfrastructureProduct]] = [ProxmoxProduct]
