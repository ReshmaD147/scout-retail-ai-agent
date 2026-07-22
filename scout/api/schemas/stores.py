"""Response schema for GET /stores (Step 15).

A small, read-only addition alongside the cart endpoints: the React
pickup-store selector (a required Step 15 UI element) needs a real list
of stores to choose from, the same way it already gets a real product
list from /chat - this is that list, for stores.
"""

from pydantic import BaseModel


class StoreSummary(BaseModel):
    store_id: str
    store_name: str
    city: str
    pickup_enabled: bool
    active: bool
