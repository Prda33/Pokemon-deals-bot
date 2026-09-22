from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus, urljoin

import requests


VINTED_API = "https://www.vinted.fr/api/v2/catalog/items"
LEBONCOIN_SEARCH = "https://www.leboncoin.fr/recherche"
CARDMARKET_PRODUCTS = (
    "https://downloads.s3.cardmarket.com/productCatalog/productList/"
    "products_singles_6.json"
)
CARDMARKET_NONSINGLES = (
    "https://downloads.s3.cardmarket.com/productCatalog/productList/"
    "products_nonsingles_6.json"
)
CARDMARKET_PRICES = (
    "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/"
    "price_guide_6.json"
)

QUERY = os.getenv("SEARCH_QUERY", "carte pokemon")
DISCOUNT_THRESHOLD = float(os.getenv("DISCOUNT_THRESHOLD", "25"))
STATE_PATH = Path(os.getenv("STATE_PATH", "state/seen.json"))
TIMEOUT = 25

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.6",
}

FOREIGN_MARKERS = {
    "japonais", "japonaise", "japanese", "anglais", "anglaise", "english",
    "allemand", "allemande", "german", "italien", "italienne", "italian",
    "coreen", "coreenne", "korean", "chinois", "chinoise", "chinese",
    "espagnol", "espagnole", "spanish", "portugais", "portugaise",
}
FRENCH_MARKERS = {"francais", "francaise", "vf", "version francaise", "carte fr"}
RISK_MARKERS = {
    "proxy", "replique", "reproduction", "fausse", "fake", "custom",
    "non officielle", "metal gold", "or plastique",
}


@dataclass
class Listing:
    source: str
    listing_id: str
    title: str
    price: float
    url: str
    image: str | None = None
    description: str = ""

    @property
    def key(self) -> str:
        return f"{self.source}:{self.listing_id}"


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def price_number(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("amount") or value.get("value")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"\d+(?:[.,]\d+)?", value.replace(" ", ""))
        if match:
            return float(match.group(0).replace(",", "."))
    return None


def first(obj: dict[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if obj.get(name) not in (None, ""):
            return obj[name]
    return None


def fetch_vinted(session: requests.Session) -> list[Listing]:
    response = session.get(
        VINTED_API,
        params={
            "search_text": QUERY,
            "order": "newest_first",
            "per_page": 40,
            "page": 1,
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    results: list[Listing] = []
    for item in data.get("items", []):
        amount = price_number(item.get("price"))
        item_id = str(item.get("id") or "")
        if not item_id or amount is None:
            continue
        photo = item.get("photo") or {}
        results.append(
            Listing(
                source="Vinted",
                listing_id=item_id,
                title=str(item.get("title") or "Annonce Pokémon"),
                description=str(item.get("description") or ""),
                price=amount,
                url=item.get("url") or f"https://www.vinted.fr/items/{item_id}",
                image=photo.get("url") or photo.get("full_size_url"),
            )
        )
    return results


def walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def listing_from_dict(obj: dict[str, Any]) -> Listing | None:
    title = first(obj, ("subject", "title", "name", "headline"))
    raw_url = first(obj, ("url", "link", "canonical_url", "web_url"))
    raw_price = first(obj, ("price", "price_cents", "amount"))
    item_id = first(obj, ("list_id", "id", "ad_id", "listing_id"))
    if not title or not raw_url or raw_price is None or item_id is None:
        return None
    raw_url = str(raw_url)
    if "leboncoin.fr" not in raw_url and not raw_url.startswith("/"):
        return None
    amount = price_number(raw_price)
    if amount is None:
        return None
    if "price_cents" in obj and amount > 1000:
        amount /= 100
    images = first(obj, ("images", "photos", "image"))
    image = None
    if isinstance(images, list) and images:
        image = images[0].get("url") if isinstance(images[0], dict) else str(images[0])
    elif isinstance(images, dict):
        image = first(images, ("url", "thumb_url", "small_url"))
    elif isinstance(images, str):
        image = images
    return Listing(
        source="Leboncoin",
        listing_id=str(item_id),
        title=str(title),
        description=str(first(obj, ("body", "description")) or ""),
        price=amount,
        url=urljoin("https://www.leboncoin.fr", raw_url),
        image=image,
    )


def fetch_leboncoin(session: requests.Session) -> list[Listing]:
    response = session.get(
        LEBONCOIN_SEARCH,
        params={"text": QUERY, "sort": "time", "order": "desc"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    html = response.text
    payloads: list[Any] = []
    for pattern in (
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
    ):
        for raw in re.findall(pattern, html, flags=re.I | re.S):
            try:
                payloads.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
    found: dict[str, Listing] = {}
    for payload in payloads:
        for obj in walk_dicts(payload):
            listing = listing_from_dict(obj)
            if listing:
                found[listing.key] = listing
    return list(found.values())[:40]


def extract_records(payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def download_json(session: requests.Session, url: str) -> Any:
    response = session.get(url, timeout=60)
    response.raise_for_status()
    return response.json()


def cardmarket_index(session: requests.Session) -> list[dict[str, Any]]:
    try:
        price_payload = download_json(session, CARDMARKET_PRICES)
        prices = {
            int(row["idProduct"]): row
            for row in extract_records(price_payload, ("priceGuides",))
            if row.get("idProduct") not in (None, "")
        }
        products: list[dict[str, Any]] = []
        for url in (CARDMARKET_PRODUCTS, CARDMARKET_NONSINGLES):
            payload = download_json(session, url)
            products.extend(extract_records(payload, ("products", "data", "items")))
        index = []
        for product in products:
            product_id = int(product.get("idProduct") or 0)
            guide = prices.get(product_id)
            if not guide:
                continue
            ref = price_number(guide.get("trend")) or price_number(guide.get("avg30"))
            ref = ref or price_number(guide.get("avg7")) or price_number(guide.get("avg"))
            if not ref or ref <= 0:
                continue
            index.append(
                {
                    "id": product_id,
                    "name": str(product.get("name") or ""),
                    "norm": norm(str(product.get("name") or "")),
                    "reference": ref,
                }
            )
        return index
    except Exception as exc:  # a quote outage must not stop marketplace checks
        print(f"Cardmarket indisponible: {exc}", file=sys.stderr)
        return []


def language_status(listing: Listing) -> str:
    text = norm(f"{listing.title} {listing.description}")
    if any(marker in text for marker in FOREIGN_MARKERS):
        return "foreign"
    if any(marker in text for marker in FRENCH_MARKERS):
        return "confirmed"
    return "likely"


def has_risk_marker(listing: Listing) -> bool:
    text = norm(f"{listing.title} {listing.description}")
    return any(marker in text for marker in RISK_MARKERS)


def best_quote(listing: Listing, index: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    title = norm(listing.title)
    if len(title) < 4:
        return None, 0.0
    title_tokens = set(title.split()) - {"pokemon", "carte", "cartes", "lot", "fr", "vf"}
    best, best_score = None, 0.0
    for product in index:
        product_norm = product["norm"]
        product_tokens = set(product_norm.split())
        overlap = len(title_tokens & product_tokens) / max(1, len(product_tokens))
        sequence = SequenceMatcher(None, title, product_norm).ratio()
        score = 0.62 * overlap + 0.38 * sequence
        if score > best_score:
            best, best_score = product, score
    return best, best_score


def evaluate(listing: Listing, index: list[dict[str, Any]]) -> dict[str, Any] | None:
    language = language_status(listing)
    if language == "foreign" or has_risk_marker(listing):
        return None
    quote, confidence = best_quote(listing, index)
    if not quote or confidence < 0.70:
        return None
    reference = float(quote["reference"])
    discount = (reference - listing.price) / reference * 100
    if discount < DISCOUNT_THRESHOLD:
        return None
    return {
        "listing": listing,
        "quote": quote,
        "confidence": confidence,
        "discount": discount,
        "language": language,
    }


def discord_alert(webhook: str, deal: dict[str, Any]) -> None:
    listing: Listing = deal["listing"]
    quote = deal["quote"]
    language_note = (
        "Français indiqué dans l’annonce"
        if deal["language"] == "confirmed"
        else "Langue française à confirmer sur les photos"
    )
    payload: dict[str, Any] = {
        "username": "Poké Deals",
        "embeds": [
            {
                "title": f"🔥 Bonne affaire potentielle — {listing.source}",
                "url": listing.url,
                "description": listing.title[:350],
                "color": 0xF2C94C,
                "fields": [
                    {"name": "Prix de l’annonce", "value": f"{listing.price:.2f} €", "inline": True},
                    {"name": "Cote estimée", "value": f"{quote['reference']:.2f} €", "inline": True},
                    {"name": "Écart", "value": f"-{deal['discount']:.0f} %", "inline": True},
                    {"name": "Correspondance", "value": quote["name"][:200], "inline": False},
                    {"name": "Langue", "value": language_note, "inline": False},
                    {
                        "name": "Avant d’acheter",
                        "value": "Vérifie le numéro, le dos, l’état et l’authenticité. Le score n’est pas une garantie.",
                        "inline": False,
                    },
                ],
                "footer": {"text": f"Confiance de correspondance : {deal['confidence'] * 100:.0f} %"},
            }
        ],
    }
    if listing.image:
        payload["embeds"][0]["thumbnail"] = {"url": listing.image}
    response = requests.post(webhook, json=payload, timeout=TIMEOUT)
    response.raise_for_status()


def discord_status(webhook: str, sources: dict[str, int]) -> None:
    requests.post(
        webhook,
        json={
            "username": "Poké Deals",
            "content": (
                "✅ **Poké Deals est actif.** Première analyse terminée : "
                + ", ".join(f"{name} {count} annonce(s)" for name, count in sources.items())
                + ". Les annonces déjà présentes ont été mémorisées pour éviter le spam."
            ),
        },
        timeout=TIMEOUT,
    ).raise_for_status()


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"initialized": False, "seen": {}}
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        state.setdefault("initialized", False)
        state.setdefault("seen", {})
        return state
    except (json.JSONDecodeError, OSError):
        return {"initialized": False, "seen": {}}


def save_state(state: dict[str, Any]) -> None:
    # Keep roughly the latest 2,000 IDs so the file remains small.
    seen = list(state["seen"].items())[-2000:]
    state["seen"] = dict(seen)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        print("DISCORD_WEBHOOK_URL manque : ajoute le secret GitHub avant de lancer le bot.")
        return 0

    session = requests.Session()
    session.headers.update(HEADERS)
    sources: dict[str, list[Listing]] = {}
    for name, fetcher in (("Vinted", fetch_vinted), ("Leboncoin", fetch_leboncoin)):
        try:
            sources[name] = fetcher(session)
            print(f"{name}: {len(sources[name])} annonce(s) lue(s)")
        except Exception as exc:
            sources[name] = []
            print(f"{name} indisponible: {exc}", file=sys.stderr)

    listings = [listing for values in sources.values() for listing in values]
    state = load_state()
    now = datetime.now(timezone.utc).isoformat()

    if not state["initialized"]:
        for listing in listings:
            state["seen"][listing.key] = now
        state["initialized"] = True
        save_state(state)
        discord_status(webhook, {name: len(values) for name, values in sources.items()})
        return 0

    new_listings = [listing for listing in listings if listing.key not in state["seen"]]
    for listing in listings:
        state["seen"][listing.key] = now

    if new_listings:
        index = cardmarket_index(session)
        for listing in new_listings:
            deal = evaluate(listing, index)
            if deal:
                discord_alert(webhook, deal)
    save_state(state)
    print(f"Nouvelles annonces: {len(new_listings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
