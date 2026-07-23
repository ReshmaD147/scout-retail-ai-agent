from scout.services import cart_service, checkout_service
from scout.services.checkout_service import ShippingAddress

PRODUCT = "FTW-004"
PICKUP_STORE = "STR-002"


def create_pickup_order(db_path: str, session_id: str = "order-session"):
    cart_service.add_item(session_id, PRODUCT, 1, db_path=db_path)
    cart_service.set_fulfillment(session_id, "pickup", PICKUP_STORE, db_path=db_path)
    review = checkout_service.create_checkout_review(session_id, db_path=db_path)
    return checkout_service.confirm_checkout(
        checkout_id=review.checkout_id,
        session_id=session_id,
        idempotency_key=f"key-{session_id}-0001",
        confirm_payment=True,
        db_path=db_path,
    )


def create_delivery_order(db_path: str, session_id: str = "delivery-order-session"):
    cart_service.add_item(session_id, PRODUCT, 1, db_path=db_path)
    cart_service.set_fulfillment(session_id, "delivery", None, db_path=db_path)
    review = checkout_service.create_checkout_review(
        session_id,
        shipping_address=ShippingAddress(
            full_name="Demo Customer",
            line1="123 Demo Street",
            city="Maple Grove",
            state="MN",
            postal_code="55311",
            country="US",
        ),
        db_path=db_path,
    )
    return checkout_service.confirm_checkout(
        checkout_id=review.checkout_id,
        session_id=session_id,
        idempotency_key=f"key-{session_id}-0001",
        confirm_payment=True,
        db_path=db_path,
    )
