"""Product repository: the only place that runs SQL against products.

See scout/repositories/__init__.py for why repositories are the sole
SQL boundary, and models.py for the Product model every method here
returns.
"""

import sqlite3
from typing import List, Optional

from scout.database.connection import connection_scope
from scout.repositories.models import Product


class ProductRepository:
    """Read access to the products table.

    Each method opens its own connection via connection_scope(), runs
    one parameterized query, converts rows to Product models, and lets
    the connection close when the `with` block exits. A repository
    instance holds no open connection between calls - it only remembers
    which database path to use.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        """
        Args:
            db_path: Optional override of the configured database path.
                Tests pass a temporary file path here so they never read
                or write the development database.
        """
        self._db_path = db_path

    def list_active(
        self,
        category: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Product]:
        """List active products, optionally filtered to one category.

        Args:
            category: Exact category name (e.g. "Footwear"). None
                returns active products across every category.
            limit: Maximum number of rows to return.
            offset: Number of matching rows to skip, for pagination.

        Returns:
            Products ordered by name. An empty list if nothing is
            active (or nothing matches the category) - this is a
            normal result, not an error.
        """
        query = "SELECT * FROM products WHERE active = 1"
        params: List[object] = []

        if category is not None:
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY name LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with connection_scope(self._db_path) as connection:
            rows = connection.execute(query, params).fetchall()

        return [Product.from_row(row) for row in rows]

    def get_by_id(self, product_id: str) -> Optional[Product]:
        """Retrieve one product by its primary key.

        Args:
            product_id: The product's product_id, e.g. "FTW-004".

        Returns:
            A Product if a row with that ID exists, otherwise None.
            A missing product is not an error here - it is up to the
            caller (a future agent or service) to decide what "product
            not found" means for its workflow. This method never raises
            just because nothing matched.
        """
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM products WHERE product_id = ?",
                (product_id,),
            ).fetchone()

        return Product.from_row(row) if row is not None else None

    def search(
        self,
        keyword: Optional[str] = None,
        category: Optional[str] = None,
        brand: Optional[str] = None,
        max_price: Optional[float] = None,
        min_rating: Optional[float] = None,
        active_only: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Product]:
        """Search products using safe, parameterized filters.

        Every filter is optional and combined with AND. All values -
        including `keyword` - are passed to sqlite3 as bound parameters
        (the "?" placeholders below), never formatted or concatenated
        into the SQL string. That is what makes this method safe from
        SQL injection: no matter what a caller passes as `keyword`
        (even a string containing SQL syntax), sqlite3 treats it purely
        as data to compare against, not as part of the query's
        structure. See the class-level note in the repository layer
        explanation for more detail.

        Args:
            keyword: Case-insensitive substring to match against name
                OR description (e.g. "running shoe").
            category: Exact category name.
            brand: Exact brand name.
            max_price: Upper bound (inclusive) on price.
            min_rating: Lower bound (inclusive) on rating.
            active_only: If True (default), only active products are
                considered.
            limit: Maximum number of rows to return.
            offset: Number of matching rows to skip.

        Returns:
            Products matching every supplied filter, ordered by name.
            An empty list if nothing matches.
        """
        conditions: List[str] = []
        params: List[object] = []

        if active_only:
            conditions.append("active = 1")
        if keyword is not None:
            conditions.append(
                "(name LIKE ? OR description LIKE ? OR subcategory LIKE ? OR attributes_json LIKE ?)"
            )
            like_value = f"%{keyword}%"
            params.extend([like_value, like_value, like_value, like_value])
        if category is not None:
            conditions.append("category = ?")
            params.append(category)
        if brand is not None:
            conditions.append("brand = ?")
            params.append(brand)
        if max_price is not None:
            conditions.append("price <= ?")
            params.append(max_price)
        if min_rating is not None:
            conditions.append("rating >= ?")
            params.append(min_rating)

        query = "SELECT * FROM products"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY name LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with connection_scope(self._db_path) as connection:
            rows: List[sqlite3.Row] = connection.execute(query, params).fetchall()

        return [Product.from_row(row) for row in rows]
