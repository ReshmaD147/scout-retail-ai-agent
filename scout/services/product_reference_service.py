"""Deterministic resolution of product references like "the first
product" or "the backpack" (Step 15).

Two distinct reference targets
--------------------------------
- Adding to a cart references the *last verified recommendation list*
  for a session (scout.repositories.recommendation_reference_repository) -
  candidates the customer has not necessarily put in a cart yet.
- Removing or updating references the *current cart's own items*
  (scout.repositories.cart_repository) - it would be wrong to resolve
  "remove the backpack" against a five-item recommendation list when
  the cart itself only has one bag in it.

Both cases share the same two resolution strategies, in order:
    1. An ordinal ("first", "2nd", "the third one") indexes directly
       into the given list, in the order it is already stored/returned.
    2. A case-insensitive substring match against each candidate's name
       (and, for cart items, nothing else needed since a cart item's
       product name is already known).

Never guesses: if nothing matches, or more than one candidate matches
a name reference, this returns a clarification request instead of
picking one arbitrarily (CLAUDE.md section 3: "Scout must never
invent... products" extends to never inventing *which* product a vague
reference meant).
"""

import re
from typing import List, Optional, Sequence, Union

from pydantic import BaseModel

_ORDINAL_WORDS = {
    "first": 1, "1st": 1, "one": 1,
    "second": 2, "2nd": 2, "two": 2,
    "third": 3, "3rd": 3, "three": 3,
    "fourth": 4, "4th": 4, "four": 4,
    "fifth": 5, "5th": 5, "five": 5,
    "sixth": 6, "6th": 6, "six": 6,
    "seventh": 7, "7th": 7, "seven": 7,
    "eighth": 8, "8th": 8, "eight": 8,
    "ninth": 9, "9th": 9, "nine": 9,
    "tenth": 10, "10th": 10, "ten": 10,
}
"""Deliberately bounded to 1-10 - Scout's demo catalog and any single
cart are both far smaller than that, so this never needs to be open-
ended. A reference beyond this range simply will not parse as an
ordinal and falls through to name matching instead."""

_DIGIT_ORDINAL_PATTERN = re.compile(r"^(\d+)(?:st|nd|rd|th)?$")


class NamedCandidate(BaseModel):
    """The minimum a candidate (a recommended product or a cart item)
    needs for reference resolution: an identifier and a name to match
    text against."""

    reference_id: str
    """The product_id (for recommendation candidates) or cart_item_id
    (for cart items) this candidate resolves to."""
    name: str


class ProductReferenceResolution(BaseModel):
    """The outcome of resolving one reference - exactly one of
    `reference_id`/`clarification` is set, never both, never neither."""

    reference_id: Optional[str] = None
    clarification: Optional[str] = None


def parse_ordinal(text: str) -> Optional[int]:
    """Parse a free-text ordinal ("first", "2nd", "3") into a 1-based
    position, or None if `text` is not an ordinal this function
    recognizes."""
    normalized = text.strip().lower()
    if normalized in _ORDINAL_WORDS:
        return _ORDINAL_WORDS[normalized]
    match = _DIGIT_ORDINAL_PATTERN.match(normalized)
    if match:
        value = int(match.group(1))
        return value if value > 0 else None
    return None


def resolve_reference(
    reference_text: str, candidates: Sequence[NamedCandidate]
) -> ProductReferenceResolution:
    """Resolve one free-text reference against an ordered candidate list.

    Args:
        reference_text: The phrase to resolve (e.g. "first product",
            "the backpack", "second item").
        candidates: The ordered list to resolve against - either a
            session's last recommendation snapshot or its current cart
            items, depending on what the caller is resolving (see
            module docstring).

    Returns:
        A ProductReferenceResolution. `clarification` is set instead of
        `reference_id` when: candidates is empty; an ordinal reference
        falls outside the candidate list's range; or a name reference
        matches zero or more than one candidate.
    """
    if not candidates:
        return ProductReferenceResolution(
            clarification="I don't have any recent products to choose from for this session. "
            "Please search for a product first."
        )

    normalized = reference_text.strip().lower()
    words = normalized.split()
    for word in words:
        position = parse_ordinal(word)
        if position is not None:
            if 1 <= position <= len(candidates):
                return ProductReferenceResolution(reference_id=candidates[position - 1].reference_id)
            return ProductReferenceResolution(
                clarification=(
                    f"There is no #{position} product in this list - I only have "
                    f"{len(candidates)} to choose from. Could you tell me which one you mean?"
                )
            )

    name_matches = [
        candidate for candidate in candidates if candidate.name.lower() in normalized or normalized in candidate.name.lower()
    ]
    if len(name_matches) == 1:
        return ProductReferenceResolution(reference_id=name_matches[0].reference_id)
    if len(name_matches) > 1:
        options = ", ".join(candidate.name for candidate in name_matches)
        return ProductReferenceResolution(
            clarification=f"I found more than one match ({options}). Which one did you mean?"
        )

    options = ", ".join(candidate.name for candidate in candidates)
    return ProductReferenceResolution(
        clarification=f"I couldn't tell which product you meant. Options are: {options}."
    )
