from .base import Connector, ConnectorError, StoreConfig
from .csv_import import parse_csv
from .shopify import ShopifyConnector
from .woocommerce import WooCommerceConnector

CONNECTORS = {
    "shopify": ShopifyConnector,
    "woocommerce": WooCommerceConnector,
    "wordpress": WooCommerceConnector,
}

__all__ = ["CONNECTORS", "Connector", "ConnectorError", "StoreConfig", "ShopifyConnector",
           "WooCommerceConnector", "parse_csv"]
