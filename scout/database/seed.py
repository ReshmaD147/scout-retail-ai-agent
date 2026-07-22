"""Synthetic demo data for the Scout retail database.

IMPORTANT: every product, brand, store, inventory quantity, and
promotion defined in this file is fictional demonstration data created
for development and testing. None of it represents a real retailer,
real product, real store, real price, or real promotion.

Seeding is idempotent: every insert uses "INSERT OR IGNORE" keyed on
each table's primary key, so calling seed_database() more than once
never creates duplicate rows and never overwrites existing data.
"""

import json
import logging
import sqlite3
from typing import Optional

from scout.database.connection import connection_scope

logger = logging.getLogger(__name__)

# Fixed timestamp for every seed row, so re-running the seed produces
# byte-identical rows instead of a new created_at/updated_at each time.
_SEED_TIMESTAMP = "2026-01-15T00:00:00+00:00"

# ---------------------------------------------------------------------------
# Stores: five fictional Scout demo stores in the Minneapolis, MN suburbs.
# ---------------------------------------------------------------------------
STORES = [
    {
        "store_id": "STR-001",
        "store_name": "Scout Demo Store - Maple Grove",
        "city": "Maple Grove",
        "state": "MN",
        "postal_code": "55369",
        "latitude": 45.0725,
        "longitude": -93.4557,
        "pickup_enabled": 1,
        "active": 1,
    },
    {
        "store_id": "STR-002",
        "store_name": "Scout Demo Store - Plymouth",
        "city": "Plymouth",
        "state": "MN",
        "postal_code": "55441",
        "latitude": 45.0105,
        "longitude": -93.4555,
        "pickup_enabled": 1,
        "active": 1,
    },
    {
        "store_id": "STR-003",
        "store_name": "Scout Demo Store - Brooklyn Park",
        "city": "Brooklyn Park",
        "state": "MN",
        "postal_code": "55443",
        "latitude": 45.0941,
        "longitude": -93.3563,
        "pickup_enabled": 1,
        "active": 1,
    },
    {
        "store_id": "STR-004",
        "store_name": "Scout Demo Store - Minnetonka",
        "city": "Minnetonka",
        "state": "MN",
        "postal_code": "55345",
        "latitude": 44.9211,
        "longitude": -93.4687,
        "pickup_enabled": 1,
        "active": 1,
    },
    {
        "store_id": "STR-005",
        "store_name": "Scout Demo Store - Eden Prairie",
        "city": "Eden Prairie",
        "state": "MN",
        "postal_code": "55344",
        "latitude": 44.8547,
        "longitude": -93.4708,
        "pickup_enabled": 1,
        "active": 1,
    },
]

# ---------------------------------------------------------------------------
# Products: 30 synthetic products across four categories.
# ---------------------------------------------------------------------------
PRODUCTS = [
    # ---------------- Footwear (10) ----------------
    {
        "product_id": "FTW-001", "name": "FlexFit Aero Runner", "brand": "FlexFit",
        "category": "Footwear", "subcategory": "Running", "price": 79.99,
        "rating": 4.5, "review_count": 312,
        "description": "Lightweight running shoe with responsive foam cushioning for daily road runs.",
        "attributes": {
            "size_options": ["7", "8", "9", "10", "11", "12"],
            "cushioning": "high", "width": "medium", "slip_resistance": "moderate",
            "use_case": "running",
        },
        "image_url": "https://images.scout-demo.local/products/FTW-001.jpg",
    },
    {
        "product_id": "FTW-002", "name": "TrailMax Ridge Hiker", "brand": "TrailMax",
        "category": "Footwear", "subcategory": "Hiking", "price": 109.99,
        "rating": 4.6, "review_count": 245,
        "description": "Waterproof mid-cut hiking boot built for uneven trails and wet conditions.",
        "attributes": {
            "size_options": ["8", "9", "10", "11", "12", "13"],
            "cushioning": "medium", "width": "wide", "slip_resistance": "high",
            "use_case": "hiking",
        },
        "image_url": "https://images.scout-demo.local/products/FTW-002.jpg",
    },
    {
        "product_id": "FTW-003", "name": "UrbanStep Daily Walker", "brand": "UrbanStep",
        "category": "Footwear", "subcategory": "Casual", "price": 64.99,
        "rating": 4.2, "review_count": 198,
        "description": "Everyday walking shoe with a breathable knit upper and cushioned insole.",
        "attributes": {
            "size_options": ["6", "7", "8", "9", "10", "11"],
            "cushioning": "medium", "width": "medium", "slip_resistance": "moderate",
            "use_case": "everyday walking",
        },
        "image_url": "https://images.scout-demo.local/products/FTW-003.jpg",
    },
    {
        "product_id": "FTW-004", "name": "ComfortPro Shift Support", "brand": "ComfortPro",
        "category": "Footwear", "subcategory": "Work", "price": 89.99,
        "rating": 4.7, "review_count": 401,
        "description": "Slip-resistant work shoe with arch support designed for long shifts on your feet.",
        "attributes": {
            "size_options": ["6", "7", "8", "9", "10", "11", "12"],
            "cushioning": "high", "width": "wide", "slip_resistance": "high",
            "use_case": "work shifts / standing all day",
        },
        "image_url": "https://images.scout-demo.local/products/FTW-004.jpg",
    },
    {
        "product_id": "FTW-005", "name": "FlexFit CloudStep Trainer", "brand": "FlexFit",
        "category": "Footwear", "subcategory": "Training", "price": 74.99,
        "rating": 4.3, "review_count": 156,
        "description": "Cross-training shoe with a stable base for lifting and lateral movement.",
        "attributes": {
            "cushioning": "medium", "width": "medium", "slip_resistance": "moderate",
            "use_case": "gym training",
        },
        "image_url": "https://images.scout-demo.local/products/FTW-005.jpg",
    },
    {
        "product_id": "FTW-006", "name": "TrailMax Summit Pro", "brand": "TrailMax",
        "category": "Footwear", "subcategory": "Trail Running", "price": 119.99,
        "rating": 4.4, "review_count": 132,
        "description": "Aggressive-tread trail running shoe for technical off-road terrain.",
        "attributes": {
            "cushioning": "high", "width": "medium", "slip_resistance": "high",
            "use_case": "trail running",
        },
        "image_url": "https://images.scout-demo.local/products/FTW-006.jpg",
    },
    {
        "product_id": "FTW-007", "name": "UrbanStep Metro Slip-On", "brand": "UrbanStep",
        "category": "Footwear", "subcategory": "Casual", "price": 54.99,
        "rating": 4.0, "review_count": 89,
        "description": "Slip-on canvas sneaker for quick, casual everyday wear.",
        "attributes": {
            "cushioning": "low", "width": "medium", "slip_resistance": "moderate",
            "use_case": "casual wear",
        },
        "image_url": "https://images.scout-demo.local/products/FTW-007.jpg",
    },
    {
        "product_id": "FTW-008", "name": "ComfortPro EasyStand Clog", "brand": "ComfortPro",
        "category": "Footwear", "subcategory": "Work", "price": 49.99,
        "rating": 4.5, "review_count": 267,
        "description": "Slip-resistant clog designed for kitchen and service-industry shifts.",
        "attributes": {
            "cushioning": "high", "width": "wide", "slip_resistance": "high",
            "use_case": "kitchen / restaurant work",
        },
        "image_url": "https://images.scout-demo.local/products/FTW-008.jpg",
    },
    {
        "product_id": "FTW-009", "name": "FlexFit AeroKnit Lite", "brand": "FlexFit",
        "category": "Footwear", "subcategory": "Lifestyle", "price": 69.99,
        "rating": 4.1, "review_count": 174,
        "description": "Ultra-light knit sneaker built for all-day comfort around town.",
        "attributes": {
            "cushioning": "medium", "width": "medium", "slip_resistance": "low",
            "use_case": "everyday comfort",
        },
        "image_url": "https://images.scout-demo.local/products/FTW-009.jpg",
    },
    {
        "product_id": "FTW-010", "name": "TrailMax CanyonGuard Boot", "brand": "TrailMax",
        "category": "Footwear", "subcategory": "Outdoor", "price": 129.99,
        "rating": 4.6, "review_count": 118,
        "description": "Insulated waterproof boot for cold-weather outdoor work and travel.",
        "attributes": {
            "cushioning": "medium", "width": "wide", "slip_resistance": "high",
            "use_case": "cold weather outdoor",
        },
        "image_url": "https://images.scout-demo.local/products/FTW-010.jpg",
    },
    # ---------------- Bags (7) ----------------
    {
        "product_id": "BAG-001", "name": "CarryNest DailyPack 20L", "brand": "CarryNest",
        "category": "Bags", "subcategory": "Backpack", "price": 59.99,
        "rating": 4.4, "review_count": 210,
        "description": "20-liter commuter backpack with a padded laptop sleeve and water-resistant shell.",
        "attributes": {
            "capacity": "20L", "material": "recycled polyester", "compartments": 3,
            "water_resistance": "water-resistant", "use_case": "daily commute",
        },
        "image_url": "https://images.scout-demo.local/products/BAG-001.jpg",
    },
    {
        "product_id": "BAG-002", "name": "TerraPack Summit 35L", "brand": "TerraPack",
        "category": "Bags", "subcategory": "Hiking Backpack", "price": 99.99,
        "rating": 4.5, "review_count": 143,
        "description": "35-liter hiking backpack with a ventilated frame for multi-hour trips.",
        "attributes": {
            "capacity": "35L", "material": "ripstop nylon", "compartments": 4,
            "water_resistance": "water-resistant", "use_case": "day hiking",
        },
        "image_url": "https://images.scout-demo.local/products/BAG-002.jpg",
    },
    {
        "product_id": "BAG-003", "name": "MetroCarry Weekender Duffel", "brand": "MetroCarry",
        "category": "Bags", "subcategory": "Duffel", "price": 74.99,
        "rating": 4.2, "review_count": 97,
        "description": "Durable weekender duffel with a separate shoe compartment.",
        "attributes": {
            "capacity": "45L", "material": "canvas", "compartments": 2,
            "water_resistance": "splash-resistant", "use_case": "weekend travel",
        },
        "image_url": "https://images.scout-demo.local/products/BAG-003.jpg",
    },
    {
        "product_id": "BAG-004", "name": "CarryNest TechSling 8L", "brand": "CarryNest",
        "category": "Bags", "subcategory": "Sling Bag", "price": 34.99,
        "rating": 4.0, "review_count": 76,
        "description": "Compact sling bag sized for a tablet, cables, and daily essentials.",
        "attributes": {
            "capacity": "8L", "material": "polyester", "compartments": 2,
            "water_resistance": "water-resistant", "use_case": "light daily carry",
        },
        "image_url": "https://images.scout-demo.local/products/BAG-004.jpg",
    },
    {
        "product_id": "BAG-005", "name": "MetroCarry Executive Briefcase", "brand": "MetroCarry",
        "category": "Bags", "subcategory": "Briefcase", "price": 89.99,
        "rating": 4.3, "review_count": 64,
        "description": "Structured laptop briefcase with a padded 15-inch sleeve for office days.",
        "attributes": {
            "capacity": "18L", "material": "vegan leather", "compartments": 4,
            "water_resistance": "not water-resistant", "use_case": "office / commute",
        },
        "image_url": "https://images.scout-demo.local/products/BAG-005.jpg",
    },
    {
        "product_id": "BAG-006", "name": "TerraPack TrailLite 15L", "brand": "TerraPack",
        "category": "Bags", "subcategory": "Day Pack", "price": 54.99,
        "rating": 4.1, "review_count": 88,
        "description": "Lightweight day pack for short hikes and everyday errands.",
        "attributes": {
            "capacity": "15L", "material": "ripstop nylon", "compartments": 2,
            "water_resistance": "water-resistant", "use_case": "short hikes / errands",
        },
        "image_url": "https://images.scout-demo.local/products/BAG-006.jpg",
    },
    {
        "product_id": "BAG-007", "name": "CarryNest UrbanTote", "brand": "CarryNest",
        "category": "Bags", "subcategory": "Tote", "price": 39.99,
        "rating": 4.2, "review_count": 121,
        "description": "Everyday tote with a reinforced base and interior organizer pockets.",
        "attributes": {
            "capacity": "22L", "material": "recycled canvas", "compartments": 3,
            "water_resistance": "not water-resistant", "use_case": "everyday carry",
        },
        "image_url": "https://images.scout-demo.local/products/BAG-007.jpg",
    },
    # ---------------- Electronics (7) ----------------
    {
        "product_id": "ELE-001", "name": "Aria SoundWave Pro Earbuds", "brand": "Aria",
        "category": "Electronics", "subcategory": "Earbuds", "price": 89.99,
        "rating": 4.4, "review_count": 522,
        "description": "True wireless earbuds with active noise cancellation and a 24-hour case battery.",
        "attributes": {
            "battery_life": "24 hours with case", "connectivity": "Bluetooth 5.3",
            "compatibility": "iOS / Android", "warranty": "1 year", "color": "black",
        },
        "image_url": "https://images.scout-demo.local/products/ELE-001.jpg",
    },
    {
        "product_id": "ELE-002", "name": "PulseTech FitBand 3", "brand": "PulseTech",
        "category": "Electronics", "subcategory": "Wearables", "price": 59.99,
        "rating": 4.1, "review_count": 288,
        "description": "Fitness tracker with heart-rate monitoring and a 10-day battery life.",
        "attributes": {
            "battery_life": "10 days", "connectivity": "Bluetooth 5.1",
            "compatibility": "iOS / Android", "warranty": "1 year", "color": "graphite",
        },
        "image_url": "https://images.scout-demo.local/products/ELE-002.jpg",
    },
    {
        "product_id": "ELE-003", "name": "EchoBeam Portable Speaker Mini", "brand": "EchoBeam",
        "category": "Electronics", "subcategory": "Speakers", "price": 44.99,
        "rating": 4.3, "review_count": 341,
        "description": "Compact splash-resistant speaker with 12 hours of playback.",
        "attributes": {
            "battery_life": "12 hours", "connectivity": "Bluetooth 5.0",
            "compatibility": "any Bluetooth device", "warranty": "1 year", "color": "blue",
        },
        "image_url": "https://images.scout-demo.local/products/ELE-003.jpg",
    },
    {
        "product_id": "ELE-004", "name": "Aria ClearView 10 Tablet", "brand": "Aria",
        "category": "Electronics", "subcategory": "Tablets", "price": 219.99,
        "rating": 4.2, "review_count": 176,
        "description": "10-inch tablet with a full-day battery for browsing, video, and reading.",
        "attributes": {
            "battery_life": "11 hours", "connectivity": "Wi-Fi",
            "compatibility": "Android apps", "warranty": "1 year", "color": "silver",
        },
        "image_url": "https://images.scout-demo.local/products/ELE-004.jpg",
    },
    {
        "product_id": "ELE-005", "name": "PulseTech PowerBank 10K", "brand": "PulseTech",
        "category": "Electronics", "subcategory": "Chargers & Power", "price": 29.99,
        "rating": 4.5, "review_count": 402,
        "description": "10,000mAh power bank with fast-charging output for phones and earbuds.",
        "attributes": {
            "battery_life": "10000mAh capacity", "connectivity": "USB-C / USB-A",
            "compatibility": "most USB devices", "warranty": "2 years", "color": "black",
        },
        "image_url": "https://images.scout-demo.local/products/ELE-005.jpg",
    },
    {
        "product_id": "ELE-006", "name": "EchoBeam HomeHub Smart Display", "brand": "EchoBeam",
        "category": "Electronics", "subcategory": "Smart Home", "price": 129.99,
        "rating": 4.0, "review_count": 93,
        "description": "Smart display for streaming, video calls, and connected-home controls.",
        "attributes": {
            "battery_life": "plugged in (no battery)", "connectivity": "Wi-Fi / Bluetooth",
            "compatibility": "major smart-home platforms", "warranty": "1 year", "color": "white",
        },
        "image_url": "https://images.scout-demo.local/products/ELE-006.jpg",
    },
    {
        "product_id": "ELE-007", "name": "Aria StudioBuds ANC", "brand": "Aria",
        "category": "Electronics", "subcategory": "Earbuds", "price": 129.99,
        "rating": 4.6, "review_count": 214,
        "description": "Premium noise-cancelling earbuds tuned for studio-quality sound.",
        "attributes": {
            "battery_life": "30 hours with case", "connectivity": "Bluetooth 5.3",
            "compatibility": "iOS / Android", "warranty": "1 year", "color": "midnight blue",
        },
        "image_url": "https://images.scout-demo.local/products/ELE-007.jpg",
    },
    # ---------------- Home and Kitchen (6) ----------------
    {
        "product_id": "HOM-001", "name": "HomeBrew DripMaster 12-Cup Coffee Maker", "brand": "HomeBrew",
        "category": "Home and Kitchen", "subcategory": "Coffee Makers", "price": 49.99,
        "rating": 4.3, "review_count": 289,
        "description": "12-cup drip coffee maker with a programmable timer and keep-warm plate.",
        "attributes": {
            "dimensions": "9 x 8 x 14 in", "material": "stainless steel / plastic",
            "power": "900W", "capacity": "12 cups", "use_case": "daily coffee brewing",
        },
        "image_url": "https://images.scout-demo.local/products/HOM-001.jpg",
    },
    {
        "product_id": "HOM-002", "name": "LumaGlow Ambient Table Lamp", "brand": "LumaGlow",
        "category": "Home and Kitchen", "subcategory": "Lighting", "price": 34.99,
        "rating": 4.4, "review_count": 167,
        "description": "Dimmable table lamp with adjustable warm-to-cool color temperature.",
        "attributes": {
            "dimensions": "7 x 7 x 18 in", "material": "brushed metal",
            "power": "9W LED", "capacity": "n/a", "use_case": "reading / ambient lighting",
        },
        "image_url": "https://images.scout-demo.local/products/HOM-002.jpg",
    },
    {
        "product_id": "HOM-003", "name": "FreshNest VacuumSeal Food Storage Set", "brand": "FreshNest",
        "category": "Home and Kitchen", "subcategory": "Food Storage", "price": 24.99,
        "rating": 4.5, "review_count": 231,
        "description": "6-piece vacuum-seal food storage set that keeps produce fresh longer.",
        "attributes": {
            "dimensions": "assorted (6 containers)", "material": "BPA-free plastic",
            "power": "manual pump", "capacity": "0.5L-2L", "use_case": "food storage / meal prep",
        },
        "image_url": "https://images.scout-demo.local/products/HOM-003.jpg",
    },
    {
        "product_id": "HOM-004", "name": "HomeBrew RapidBoil Electric Kettle", "brand": "HomeBrew",
        "category": "Home and Kitchen", "subcategory": "Kettles", "price": 29.99,
        "rating": 4.6, "review_count": 356,
        "description": "1.7-liter electric kettle that boils water in under five minutes.",
        "attributes": {
            "dimensions": "8 x 6 x 9 in", "material": "stainless steel",
            "power": "1500W", "capacity": "1.7L", "use_case": "boiling water quickly",
        },
        "image_url": "https://images.scout-demo.local/products/HOM-004.jpg",
    },
    {
        "product_id": "HOM-005", "name": "LumaGlow NightPath LED Strip", "brand": "LumaGlow",
        "category": "Home and Kitchen", "subcategory": "Lighting", "price": 19.99,
        "rating": 4.1, "review_count": 142,
        "description": "Motion-activated LED strip lighting for hallways and stairs.",
        "attributes": {
            "dimensions": "10 ft strip", "material": "flexible silicone",
            "power": "5W", "capacity": "n/a", "use_case": "night lighting",
        },
        "image_url": "https://images.scout-demo.local/products/HOM-005.jpg",
    },
    {
        "product_id": "HOM-006", "name": "FreshNest ChillBox Mini Fridge 3.2 cu ft", "brand": "FreshNest",
        "category": "Home and Kitchen", "subcategory": "Small Appliances", "price": 119.99,
        "rating": 4.2, "review_count": 78,
        "description": "Compact 3.2 cubic-foot fridge for dorms, offices, or bonus rooms.",
        "attributes": {
            "dimensions": "19 x 18 x 33 in", "material": "steel",
            "power": "70W", "capacity": "3.2 cu ft", "use_case": "compact refrigeration",
        },
        "image_url": "https://images.scout-demo.local/products/HOM-006.jpg",
    },
]

# ---------------------------------------------------------------------------
# Inventory: deliberately varied availability across the 5 demo stores.
# Each row: (product_id, store_id, quantity_available, quantity_reserved,
#            pickup_ready_minutes, restock_date)
# ---------------------------------------------------------------------------
INVENTORY = [
    # FTW-001: widely available, including Maple Grove.
    ("FTW-001", "STR-001", 15, 1, 30, None),
    ("FTW-001", "STR-002", 10, 0, 45, None),
    ("FTW-001", "STR-004", 6, 0, 60, None),
    # FTW-002: out at Maple Grove with a future restock, available nearby.
    ("FTW-002", "STR-001", 0, 0, None, "2026-08-10"),
    ("FTW-002", "STR-003", 9, 0, 50, None),
    ("FTW-002", "STR-004", 4, 0, 60, None),
    # FTW-003: available at Maple Grove and Eden Prairie.
    ("FTW-003", "STR-001", 12, 0, 30, None),
    ("FTW-003", "STR-005", 5, 0, 70, None),
    # FTW-004 (Scout's primary workflow example): out at Maple Grove,
    # available nearby in Plymouth and Brooklyn Park.
    ("FTW-004", "STR-001", 0, 0, None, None),
    ("FTW-004", "STR-002", 8, 1, 45, None),
    ("FTW-004", "STR-003", 3, 0, 50, None),
    # FTW-005: low inventory at Maple Grove only.
    ("FTW-005", "STR-001", 2, 0, 30, None),
    # FTW-006: not carried at Maple Grove at all; available in Plymouth/Minnetonka.
    ("FTW-006", "STR-002", 7, 0, 40, None),
    ("FTW-006", "STR-004", 3, 0, 55, None),
    # FTW-007: strong availability at Maple Grove and Brooklyn Park.
    ("FTW-007", "STR-001", 20, 2, 30, None),
    ("FTW-007", "STR-003", 10, 0, 45, None),
    # FTW-008: low inventory at Maple Grove, more in Plymouth.
    ("FTW-008", "STR-001", 1, 0, 90, None),
    ("FTW-008", "STR-002", 6, 0, 45, None),
    # FTW-009: not carried at Maple Grove; available in Minnetonka/Eden Prairie.
    ("FTW-009", "STR-004", 8, 0, 50, None),
    ("FTW-009", "STR-005", 4, 0, 65, None),
    # FTW-010: zero local availability everywhere it is tracked, with a
    # far-future restock date.
    ("FTW-010", "STR-001", 0, 0, None, "2026-09-01"),
    ("FTW-010", "STR-002", 0, 0, None, "2026-09-01"),

    # BAG-001: available at Maple Grove and Plymouth.
    ("BAG-001", "STR-001", 18, 1, 30, None),
    ("BAG-001", "STR-002", 9, 0, 45, None),
    # BAG-002: available at Maple Grove and Minnetonka.
    ("BAG-002", "STR-001", 5, 0, 35, None),
    ("BAG-002", "STR-004", 6, 0, 55, None),
    # BAG-003: not carried at Maple Grove; available in Plymouth/Brooklyn Park.
    ("BAG-003", "STR-002", 7, 0, 45, None),
    ("BAG-003", "STR-003", 4, 0, 50, None),
    # BAG-004: available only at Maple Grove.
    ("BAG-004", "STR-001", 10, 0, 30, None),
    # BAG-005: zero availability at every tracked store (discontinued /
    # awaiting resupply, no known restock date).
    ("BAG-005", "STR-001", 0, 0, None, None),
    ("BAG-005", "STR-002", 0, 0, None, None),
    ("BAG-005", "STR-003", 0, 0, None, None),
    ("BAG-005", "STR-004", 0, 0, None, None),
    ("BAG-005", "STR-005", 0, 0, None, None),
    # BAG-006: not carried at Maple Grove; available in Brooklyn Park/Eden Prairie.
    ("BAG-006", "STR-003", 6, 0, 45, None),
    ("BAG-006", "STR-005", 3, 0, 65, None),
    # BAG-007: available at Maple Grove and Eden Prairie.
    ("BAG-007", "STR-001", 14, 0, 30, None),
    ("BAG-007", "STR-005", 7, 0, 65, None),

    # ELE-001: strong availability across three stores.
    ("ELE-001", "STR-001", 25, 2, 30, None),
    ("ELE-001", "STR-002", 15, 0, 45, None),
    ("ELE-001", "STR-003", 10, 0, 50, None),
    # ELE-002: available at Maple Grove and Minnetonka.
    ("ELE-002", "STR-001", 6, 0, 30, None),
    ("ELE-002", "STR-004", 4, 0, 55, None),
    # ELE-003: not carried at Maple Grove; available in Plymouth/Eden Prairie.
    ("ELE-003", "STR-002", 9, 0, 40, None),
    ("ELE-003", "STR-005", 5, 0, 65, None),
    # ELE-004: out at Maple Grove with a future restock, available in Minnetonka.
    ("ELE-004", "STR-001", 0, 0, None, "2026-08-20"),
    ("ELE-004", "STR-004", 3, 0, 60, None),
    # ELE-005: cheap accessory, widely stocked at every demo store.
    ("ELE-005", "STR-001", 30, 0, 30, None),
    ("ELE-005", "STR-002", 20, 0, 45, None),
    ("ELE-005", "STR-003", 12, 0, 50, None),
    ("ELE-005", "STR-004", 8, 0, 55, None),
    ("ELE-005", "STR-005", 10, 0, 65, None),
    # ELE-006: niche smart-home item, low inventory, not at Maple Grove.
    ("ELE-006", "STR-003", 4, 0, 50, None),
    ("ELE-006", "STR-004", 2, 0, 55, None),
    # ELE-007: low inventory at Maple Grove, more in Plymouth.
    ("ELE-007", "STR-001", 3, 0, 30, None),
    ("ELE-007", "STR-002", 5, 0, 45, None),

    # HOM-001: available at Maple Grove and Plymouth.
    ("HOM-001", "STR-001", 12, 0, 30, None),
    ("HOM-001", "STR-002", 8, 0, 45, None),
    # HOM-002: available at Maple Grove and Eden Prairie.
    ("HOM-002", "STR-001", 9, 0, 30, None),
    ("HOM-002", "STR-005", 4, 0, 65, None),
    # HOM-003: not carried at Maple Grove; available in Plymouth/Brooklyn Park.
    ("HOM-003", "STR-002", 11, 0, 45, None),
    ("HOM-003", "STR-003", 6, 0, 50, None),
    # HOM-004: out at Maple Grove with a future restock, available in Minnetonka.
    ("HOM-004", "STR-001", 0, 0, None, "2026-08-05"),
    ("HOM-004", "STR-004", 7, 0, 55, None),
    # HOM-005: available at Maple Grove and Brooklyn Park.
    ("HOM-005", "STR-001", 20, 0, 30, None),
    ("HOM-005", "STR-003", 10, 0, 50, None),
    # HOM-006: bulky appliance, low inventory, not at Maple Grove.
    ("HOM-006", "STR-004", 2, 0, 60, None),
    ("HOM-006", "STR-005", 1, 0, 70, None),
]

# ---------------------------------------------------------------------------
# Promotions: a mix of active, inactive, future, and expired records.
# The "active" flag is a manual on/off switch set by merchandising and is
# independent from the start_date/end_date range - a promotion can have
# active=1 but an expired date range, or active=0 during a currently
# valid date range. Reconciling the two into a single "is this promotion
# usable right now" answer is service-layer logic for a later phase.
# ---------------------------------------------------------------------------
PROMOTIONS = [
    {
        "promotion_id": "PRM-001", "product_id": "FTW-001", "label": "Summer Running Sale",
        "discount_percent": 15.0, "discount_amount": None,
        "start_date": "2026-07-01", "end_date": "2026-08-15", "active": 1,
    },
    {
        "promotion_id": "PRM-002", "product_id": "FTW-004", "label": "Workwear Comfort Event",
        "discount_percent": 10.0, "discount_amount": None,
        "start_date": "2026-07-10", "end_date": "2026-07-31", "active": 1,
    },
    {
        "promotion_id": "PRM-003", "product_id": "BAG-001", "label": "Back to Commute Deal",
        "discount_percent": None, "discount_amount": 10.00,
        "start_date": "2026-06-01", "end_date": "2026-06-30", "active": 1,
    },
    {
        "promotion_id": "PRM-004", "product_id": "ELE-001", "label": "Audio Flash Sale",
        "discount_percent": 20.0, "discount_amount": None,
        "start_date": "2026-09-01", "end_date": "2026-09-10", "active": 1,
    },
    {
        "promotion_id": "PRM-005", "product_id": "HOM-004", "label": "Kitchen Refresh",
        "discount_percent": 12.0, "discount_amount": None,
        "start_date": "2026-07-15", "end_date": "2026-08-01", "active": 1,
    },
    {
        "promotion_id": "PRM-006", "product_id": "FTW-008", "label": "Service Industry Discount",
        "discount_percent": None, "discount_amount": 5.00,
        "start_date": "2026-07-01", "end_date": "2026-07-31", "active": 0,
    },
    {
        "promotion_id": "PRM-007", "product_id": "ELE-005", "label": "Power Up Bundle",
        "discount_percent": 25.0, "discount_amount": None,
        "start_date": "2026-06-15", "end_date": "2026-07-05", "active": 1,
    },
    {
        "promotion_id": "PRM-008", "product_id": "BAG-002", "label": "Trailhead Preview",
        "discount_percent": 10.0, "discount_amount": None,
        "start_date": "2026-08-01", "end_date": "2026-08-20", "active": 1,
    },
    {
        "promotion_id": "PRM-009", "product_id": "FTW-002", "label": "Hiking Season Kickoff",
        "discount_percent": None, "discount_amount": 15.00,
        "start_date": "2026-05-01", "end_date": "2026-05-31", "active": 0,
    },
    {
        "promotion_id": "PRM-010", "product_id": "HOM-001", "label": "Coffee Lovers Discount",
        "discount_percent": 8.0, "discount_amount": None,
        "start_date": "2026-07-01", "end_date": "2026-07-25", "active": 1,
    },
]


def _seed_stores(connection: sqlite3.Connection) -> None:
    connection.executemany(
        """
        INSERT OR IGNORE INTO stores (
            store_id, store_name, city, state, postal_code,
            latitude, longitude, pickup_enabled, active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                s["store_id"], s["store_name"], s["city"], s["state"], s["postal_code"],
                s["latitude"], s["longitude"], s["pickup_enabled"], s["active"],
            )
            for s in STORES
        ],
    )


def _seed_products(connection: sqlite3.Connection) -> None:
    connection.executemany(
        """
        INSERT OR IGNORE INTO products (
            product_id, name, brand, category, subcategory, description,
            price, rating, review_count, attributes_json, image_url,
            active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                p["product_id"], p["name"], p["brand"], p["category"], p["subcategory"],
                p["description"], p["price"], p["rating"], p["review_count"],
                json.dumps(p["attributes"], separators=(",", ":")), p["image_url"],
                1, _SEED_TIMESTAMP, _SEED_TIMESTAMP,
            )
            for p in PRODUCTS
        ],
    )


def _seed_inventory(connection: sqlite3.Connection) -> None:
    connection.executemany(
        """
        INSERT OR IGNORE INTO inventory (
            product_id, store_id, quantity_available, quantity_reserved,
            pickup_ready_minutes, restock_date, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (product_id, store_id, qty_available, qty_reserved, pickup_minutes, restock_date, _SEED_TIMESTAMP)
            for product_id, store_id, qty_available, qty_reserved, pickup_minutes, restock_date in INVENTORY
        ],
    )


def _seed_promotions(connection: sqlite3.Connection) -> None:
    connection.executemany(
        """
        INSERT OR IGNORE INTO promotions (
            promotion_id, product_id, label, discount_percent, discount_amount,
            start_date, end_date, active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                pr["promotion_id"], pr["product_id"], pr["label"], pr["discount_percent"],
                pr["discount_amount"], pr["start_date"], pr["end_date"], pr["active"],
            )
            for pr in PROMOTIONS
        ],
    )


def seed_database(db_path: Optional[str] = None) -> None:
    """Insert all synthetic demo data. Safe to call more than once.

    Args:
        db_path: Optional override of the configured database path,
            used by tests to target a temporary file.
    """
    with connection_scope(db_path) as connection:
        _seed_stores(connection)
        _seed_products(connection)
        _seed_inventory(connection)
        _seed_promotions(connection)

    logger.info(
        "database_seeded",
        extra={
            "stores": len(STORES),
            "products": len(PRODUCTS),
            "inventory_rows": len(INVENTORY),
            "promotions": len(PROMOTIONS),
        },
    )


if __name__ == "__main__":
    seed_database()
    print(
        f"Seeded {len(STORES)} stores, {len(PRODUCTS)} products, "
        f"{len(INVENTORY)} inventory rows, {len(PROMOTIONS)} promotions."
    )
