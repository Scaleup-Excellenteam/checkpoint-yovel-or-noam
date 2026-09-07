# TSPO DLP Policy: Protect the Secret Slice

## Purpose

The chat server must prevent prohibited pineapple references and pizza-recipe
information from being distributed or stored. DLP decisions are made by the
server, before a message reaches another client or SQLite.

## Decision order

Each incoming chat message is checked in this order. The first matching rule
stops the process and blocks the message.

1. Normalize the text.
2. Check prohibited pineapple terms.
3. Check explicit secret markers.
4. Check recipe-declaration terms.
5. Check recipe-like structure.
6. Allow the message when no rule matches.

## Normalization

Before matching, the server should:

- Convert English text to lowercase.
- Remove leading and trailing whitespace.
- Treat repeated whitespace as one space.
- Keep the original message unchanged for the user, but use the normalized
  version only for matching.

The server must not write a blocked message's original content to its logs.

## Rule 1: Pineapple is always prohibited

Block a message containing either term below, regardless of context:

```text
אננס
pineapple
```

Examples:

```text
"I want pineapple on my pizza"  -> BLOCK
"אין אננס במטבח"                 -> BLOCK
```

Reason code:

```text
DLP_FORBIDDEN_PINEAPPLE
```

## Rule 2: Explicit TSPO secrets

Block a message containing any configured TSPO secret marker. The initial
markers are:

```text
TSPO_SECRET_RECIPE
TSPO_SECRET_SAUCE
TSPO_DOUGH_FORMULA
VAULT_CODE
SECRET_RECIPE
SECRET_SAUCE
```

These are controlled demo secrets. Real secrets must never be committed to the
repository or copied into tests.

Reason code:

```text
DLP_EXPLICIT_SECRET
```

## Rule 3: Recipe declarations

Block a message containing any declaration that it reveals a recipe or secret
preparation method:

```text
מתכון
המתכון
מרכיבים
הוראות הכנה
recipe
ingredients
instructions
secret recipe
secret sauce
בצק סודי
רוטב סודי
```

Reason code:

```text
DLP_RECIPE_DECLARATION
```

## Rule 4: Recipe-like structure

Block a message even when it does not contain the word "recipe" if it has both
of the following:

1. A pizza ingredient term, and
2. A quantity or preparation-action term.

Ingredient terms initially include:

```text
dough, crust, sauce, mozzarella, cheese, pepperoni, olives, mushrooms,
tomato, garlic, basil, oregano, onion, בצק, רוטב, גבינה, מוצרלה, זיתים,
פטריות, עגבניות, שום, בזיליקום, אורגנו, בצל
```

Quantity terms include:

```text
גרם, קילו, כוס, כפית, כף, ml, kg, grams, cup, teaspoon, tablespoon
```

Preparation-action terms include:

```text
ללוש, לערבב, לאפות, לחמם, להוסיף, mix, knead, bake, heat, add
```

Example:

```text
"מערבבים את הרוטב ואז אופים"  -> BLOCK
"add sauce and bake"          -> BLOCK
```

Reason code:

```text
DLP_RECIPE_STRUCTURE
```

## Allowed examples

Normal pizza conversation is allowed when it does not match a blocking rule:

```text
"I like mozzarella and olives"
"אני רוצה פיצה עם זיתים"
"pepperoni is my favorite topping"
```

## Enforcement action

For every DLP block, the server must:

1. Send a short response to the sender, for example:

   ```text
   Message blocked: DLP_RECIPE_STRUCTURE
   ```

2. Do not call `save_message()`.
3. Do not call `broadcast_to_room()`.
4. Log safe metadata only:

   ```text
   DLP blocked: user=yovel room=general reason=DLP_RECIPE_STRUCTURE
   ```

5. Count the violation for the current connection.
6. Close the connection after three DLP blocks:

   ```text
   Too many DLP violations - connection closed
   ```

## Required tests

The project must have automated tests proving that:

- `pineapple` and `אננס` are blocked.
- Every explicit TSPO secret marker is blocked.
- Recipe-declaration words are blocked.
- An ingredient plus a quantity/action is blocked.
- An ordinary pizza message is allowed.
- A blocked message is neither saved nor delivered to another client.
- A third DLP violation closes the sender's connection.

## Limitation and next improvement

This keyword-and-pattern policy cannot identify every possible indirect recipe
description or deliberate spelling evasion. It is intentionally conservative
for a clear classroom demo. A future version could add additional language
variants and a reviewed rule-management screen.
