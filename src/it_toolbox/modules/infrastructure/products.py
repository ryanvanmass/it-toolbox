"""The Infrastructure module's products, in tree-root order.

Each entry is an InfrastructureProduct subclass (see product.py). Planned
roots: TrueNAS, Proxmox, PBS -- each lands with its own PR.
"""

from it_toolbox.modules.infrastructure.pbs_product import PbsProduct
from it_toolbox.modules.infrastructure.product import InfrastructureProduct

PRODUCT_CLASSES: list[type[InfrastructureProduct]] = [PbsProduct]
