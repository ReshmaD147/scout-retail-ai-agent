"""Tests for scout/agents/cart_command_agent.py (Step 15).

Covers the exact natural-language examples the Step 15 prompt lists
("The LLM may understand commands such as...") plus the safe fallback
for anything unrecognized. This module is deterministic parsing only
(see its module docstring) - none of these tests touch a database or
validate whether the parsed command is actually executable; that is
scout/services/cart_service.py's job, tested separately.
"""

from scout.agents.cart_command_agent import parse_cart_command


def test_parses_add_first_product():
    command = parse_cart_command("Add the first product to my cart.")
    assert command.action == "add"
    assert command.product_reference == "first product"
    assert command.quantity == 1


def test_parses_add_with_quantity_and_ordinal():
    command = parse_cart_command("Add two of the second item.")
    assert command.action == "add"
    assert command.product_reference == "second item"
    assert command.quantity == 2


def test_parses_update_quantity():
    command = parse_cart_command("Change the quantity to three.")
    assert command.action == "update_quantity"
    assert command.quantity == 3
    assert command.product_reference is None


def test_parses_remove_by_name():
    command = parse_cart_command("Remove the backpack.")
    assert command.action == "remove"
    assert command.product_reference == "backpack"


def test_parses_pickup_with_store():
    command = parse_cart_command("Use pickup at Maple Grove.")
    assert command.action == "set_fulfillment"
    assert command.fulfillment_type == "pickup"
    assert command.store_reference == "Maple Grove"


def test_parses_switch_to_delivery():
    command = parse_cart_command("Switch to delivery.")
    assert command.action == "set_fulfillment"
    assert command.fulfillment_type == "delivery"
    assert command.store_reference is None


def test_parses_clear_cart():
    command = parse_cart_command("Please clear my cart.")
    assert command.action == "clear"


def test_unrecognized_command_returns_unknown_action():
    command = parse_cart_command("What's the weather like today?")
    assert command.action == "unknown"
    assert command.product_reference is None
    assert command.quantity is None
    assert command.fulfillment_type is None
