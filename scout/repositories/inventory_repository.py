"""Inventory repository: the only place that runs SQL against inventory."""

from typing import List, Optional

from scout.database.connection import connection_scope
from scout.repositories.models import InventoryRecord


class InventoryRepository:
    """Read access to the inventory table."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """
        Args:
            db_path: Optional override of the configured database path.
                Tests pass a temporary file path here.
        """
        self._db_path = db_path

    def get_for_product_and_store(
        self, product_id: str, store_id: str
    ) -> Optional[InventoryRecord]:
        """Retrieve the inventory row for one product at one store.

        Args:
            product_id: The product's primary key.
            store_id: The store's primary key.

        Returns:
            An InventoryRecord if a row exists for that exact
            (product, store) pair, otherwise None.

            Note the distinction this preserves: a product that is
            tracked at a store with quantity_available = 0 returns a
            real InventoryRecord (out of stock, but tracked). A product
            that was never tracked at that store at all (no row)
            returns None. Collapsing those two cases would hide useful
            information from later inventory/fulfillment logic - e.g.
            "out of stock, restocking Aug 10" versus "not carried at
            this store."
        """
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM inventory WHERE product_id = ? AND store_id = ?",
                (product_id, store_id),
            ).fetchone()

        return InventoryRecord.from_row(row) if row is not None else None

    def list_for_product(self, product_id: str) -> List[InventoryRecord]:
        """List every store's inventory row for one product.

        This is the natural companion to get_for_product_and_store: it
        answers "which stores carry this product at all, and how much
        do they have" in a single call - something later fulfillment
        logic needs when comparing the customer's selected store
        against alternatives.

        Args:
            product_id: The product's primary key.

        Returns:
            InventoryRecord entries, one per store with a tracked row
            for this product, ordered by store_id. Empty list if the
            product has no inventory rows anywhere.
        """
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM inventory WHERE product_id = ? ORDER BY store_id",
                (product_id,),
            ).fetchall()

        return [InventoryRecord.from_row(row) for row in rows]
