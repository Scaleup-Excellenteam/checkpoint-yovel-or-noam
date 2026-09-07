"""Server-side DLP rules for the TSPO chat.

The scanner returns a reason code only. It never returns or logs blocked text.
"""

from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class DLPDecision:
    allowed: bool
    reason_code: str | None = None


ALLOW = DLPDecision(allowed=True)


def normalize_message(message: str) -> str:
    """Normalize harmless formatting differences before matching text rules."""
    normalized = unicodedata.normalize("NFKC", message).casefold().strip()
    return re.sub(r"\s+", " ", normalized)


class DLPScanner:
    """Apply the documented TSPO policy in a deterministic order."""

    forbidden_pineapple_terms = ("אננס", "pineapple")
    explicit_secret_markers = (
        "tspo_secret_recipe",
        "tspo_secret_sauce",
        "tspo_dough_formula",
        "vault_code",
        "secret_recipe",
        "secret_sauce",
    )
    recipe_declaration_terms = (
        "מתכון",
        "המתכון",
        "מרכיבים",
        "הוראות הכנה",
        "recipe",
        "ingredients",
        "instructions",
        "secret recipe",
        "secret sauce",
        "בצק סודי",
        "רוטב סודי",
    )
    ingredient_terms = (
        "dough",
        "crust",
        "sauce",
        "mozzarella",
        "cheese",
        "pepperoni",
        "olives",
        "mushrooms",
        "tomato",
        "garlic",
        "basil",
        "oregano",
        "onion",
        "בצק",
        "רוטב",
        "גבינה",
        "מוצרלה",
        "זיתים",
        "פטריות",
        "עגבניות",
        "שום",
        "בזיליקום",
        "אורגנו",
        "בצל",
    )
    quantity_terms = (
        "גרם",
        "קילו",
        "כוס",
        "כפית",
        "כף",
        "ml",
        "kg",
        "grams",
        "cup",
        "teaspoon",
        "tablespoon",
    )
    preparation_terms = (
        "ללוש",
        "לערבב",
        "לאפות",
        "לחמם",
        "להוסיף",
        "mix",
        "knead",
        "bake",
        "heat",
        "add",
    )

    def scan(self, message: str) -> DLPDecision:
        """Return the first matching DLP decision without retaining the message."""
        normalized = normalize_message(message)

        if any(term in normalized for term in self.forbidden_pineapple_terms):
            return DLPDecision(False, "DLP_FORBIDDEN_PINEAPPLE")
        if any(term in normalized for term in self.explicit_secret_markers):
            return DLPDecision(False, "DLP_EXPLICIT_SECRET")
        if any(term in normalized for term in self.recipe_declaration_terms):
            return DLPDecision(False, "DLP_RECIPE_DECLARATION")

        contains_ingredient = any(term in normalized for term in self.ingredient_terms)
        contains_recipe_signal = any(
            term in normalized for term in (*self.quantity_terms, *self.preparation_terms)
        )
        if contains_ingredient and contains_recipe_signal:
            return DLPDecision(False, "DLP_RECIPE_STRUCTURE")

        return ALLOW
