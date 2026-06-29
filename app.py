"""
Trade Buddy — one vision call per trade.

A kid lays out their stuff on the red tile and the trade partner's on the yellow
tile, snapping a photo of each. The model identifies every item across both
piles and returns a single impartial fairness judgment (leaning GENEROUS); the
app writes the kid-facing words in code. Works for any trading cards or the small
collectibles and toys kids swap.

One Railway service: serves the PWA from /static and handles POST /check.
"""

import os
import json
import time
import random
import logging
import threading
from collections import deque

import anthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("trade")

# Sonnet 4.6 is the default — great item-ID vision at ~$0.03–0.07/check.
# Flip to Haiku 4.5 (claude-haiku-4-5) via the MODEL env var to test cheaper.
MODEL = os.environ.get("MODEL", "claude-sonnet-4-6")

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

app = FastAPI()

# --- cost tracking ---------------------------------------------------------
# USD per 1M tokens (input, output). Estimate only — Anthropic Console is the
# source of truth for billing.
PRICING = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5":  (1.0, 5.0),
    "claude-opus-4-8":   (5.0, 25.0),
}
STATS_KEY = os.environ.get("STATS_KEY")          # optional: gate /stats + /dashboard
DATA_DIR = os.environ.get("DATA_DIR", "data")    # set to a Railway volume to persist
STATS_FILE = os.path.join(DATA_DIR, "stats.json")

_lock = threading.Lock()
_stats = {"checks": 0, "in_tokens": 0, "out_tokens": 0, "cost": 0.0, "by_model": {}}
_recent = deque(maxlen=50)


def _cost(model, i, o):
    pin, pout = PRICING.get(model, (0.0, 0.0))
    return i / 1e6 * pin + o / 1e6 * pout


def _save_stats():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(STATS_FILE, "w") as f:
            json.dump({"totals": _stats, "recent": list(_recent)}, f)
    except Exception as e:
        log.warning("stats save failed: %s", e)


def _load_stats():
    try:
        with open(STATS_FILE) as f:
            d = json.load(f)
        _stats.update(d.get("totals", {}))
        for e in reversed(d.get("recent", [])):
            _recent.appendleft(e)
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning("stats load failed: %s", e)


def _record(model, verdict, i, o):
    c = _cost(model, i, o)
    with _lock:
        _stats["checks"] += 1
        _stats["in_tokens"] += i
        _stats["out_tokens"] += o
        _stats["cost"] += c
        m = _stats["by_model"].setdefault(
            model, {"checks": 0, "in_tokens": 0, "out_tokens": 0, "cost": 0.0})
        m["checks"] += 1
        m["in_tokens"] += i
        m["out_tokens"] += o
        m["cost"] += c
        _recent.appendleft({"ts": time.time(), "model": model, "verdict": verdict,
                            "in": i, "out": o, "cost": round(c, 6)})
        _save_stats()


def _require_key(key):
    if STATS_KEY and key != STATS_KEY:
        raise HTTPException(status_code=403, detail="forbidden")


# --- spend guardrails ------------------------------------------------------
# Hard daily money ceiling + per-user daily call cap. Both reset at UTC midnight.
def _env_num(name, default, cast):
    raw = os.environ.get(name)
    if raw is None:
        return default
    cleaned = raw.strip().lstrip("$").replace(",", "").strip()
    try:
        return cast(cleaned)
    except (ValueError, TypeError):
        log.warning("bad %s=%r, using default %r", name, raw, default)
        return default


DAILY_BUDGET_USD = _env_num("DAILY_BUDGET_USD", 5.0, float)
PER_USER_DAILY = _env_num("PER_USER_DAILY", 50, int)
_day = {"date": "", "spend": 0.0, "ips": {}}


def _today():
    return time.strftime("%Y-%m-%d", time.gmtime())


def _roll_day():
    t = _today()
    if _day["date"] != t:
        _day["date"], _day["spend"], _day["ips"] = t, 0.0, {}


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _limit_block(ip: str):
    """Return 'budget' or 'user' if this request should be refused, else None."""
    with _lock:
        _roll_day()
        if _day["spend"] >= DAILY_BUDGET_USD:
            return "budget"
        if _day["ips"].get(ip, 0) >= PER_USER_DAILY:
            return "user"
    return None


def _charge_day(ip: str, cost: float):
    with _lock:
        _roll_day()
        _day["spend"] += cost
        _day["ips"][ip] = _day["ips"].get(ip, 0) + 1


def _blocked_result(headline: str) -> dict:
    return {"cards_found": False, "verdict": "stop", "face": "sleeping",
            "headline": headline, "gem_alert": False, "gem_note": "",
            "red_cards": [], "yellow_cards": []}


_load_stats()

# --- the kid-facing prompt -------------------------------------------------

SYSTEM = """You help two kids check whether a trade between friends is a good,
friendly one. The items are trading cards (any game: Pokemon, Magic, Yu-Gi-Oh,
sports cards, and so on) or the small collectibles and toys kids swap (Beyblades,
mini-figures, blind-box figures, small figurines, and the like). You are NOT a
price guide; most of this stuff is played-with and worth little.

The simple test: would a good buddy feel happy making this trade, and would their
friend feel happy too? If both kids would walk away smiling, it is fair. You are
not balancing exact value. You only flag the trades a friend would actually
regret: a clearly lopsided deal, or trading away something genuinely valuable by
mistake. Friends give each other the benefit of the doubt, so default hard to
"fair."

The two sides are RED and YELLOW, named after the two photo tiles:
  1. First photo  = RED's stuff.
  2. Second photo = YELLOW's stuff.
A trade swaps Red's items for Yellow's items. Judge it impartially between the
two sides. You ONLY return structured judgment; the app writes the words a child
sees, so do not write any sentences yourself.

For every item you can make out, give a short name and a rough tier:
  - "junk"     : common, played, the vast majority of items.
  - "ok"       : a little better, a popular or slightly-above-common item.
  - "nice"     : clearly desirable (a holo/shiny/full-art card, a sought-after
                 figure). Cool, but not real money. Most "good" items land here.
  - "treasure" : genuinely valuable. A vintage or first-edition card, a rare
                 chase card, a rare or limited collectible or figure, anything
                 that looks like real money. These are RARE. Being shiny or cool
                 does NOT automatically make something a treasure. Judge the item,
                 not just the shine.

Return these fields:
  - cards_found : true ONLY if BOTH photos clearly show real tradeable items
                  (cards, toys, figures). If either photo shows something that is
                  NOT a tradeable item (a random household object, a pen, a hand,
                  an empty table) or is too blurry to tell, set this FALSE. When
                  false, the trade is not judged and the other fields don't matter.
  - red_cards / yellow_cards : the items on each side, each {name, tier}.
  - verdict :
      * "fair"   : even, close enough, or both sides get cool stuff. Most trades.
                   Junk-for-junk is fair.
      * "uneven" : one side is clearly giving more or better than the other. A
                   tier gap counts: a "nice" item traded for only "junk" is
                   UNEVEN, not fair. A nudge, not a stop.
      * "stop"   : a "treasure"-tier (real-money) item is on either side. A
                   grown-up should look before anyone trades.
  - heavier : which side is giving the more valuable pile: "red", "yellow", or
              "even". For a fair trade this is usually "even".
  - special_side : the side holding the single most special item: "red",
                   "yellow", or "none". Set whenever a "nice" or "treasure" item
                   is the reason the trade is not plain junk-for-junk.
  - fake_warning : true ONLY if a card or item looks clearly fake (wrong fonts,
                   off colors, misspelled text). Be unsure and gentle, never
                   accusatory.

LEAN GENEROUS: these are little kids and the point is to let friends trade and
have fun. When in doubt, say "fair". If you don't clearly see tradeable items on
BOTH sides, set cards_found false.
"""

_CARD_ARRAY = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "tier": {"type": "string", "enum": ["junk", "ok", "nice", "treasure"]},
        },
        "required": ["name", "tier"],
        "additionalProperties": False,
    },
}

SCHEMA = {
    "type": "object",
    "properties": {
        "cards_found": {"type": "boolean"},
        "verdict": {"type": "string", "enum": ["fair", "uneven", "stop"]},
        "heavier": {"type": "string", "enum": ["red", "yellow", "even"]},
        "special_side": {"type": "string", "enum": ["red", "yellow", "none"]},
        "fake_warning": {"type": "boolean"},
        "red_cards": _CARD_ARRAY,
        "yellow_cards": _CARD_ARRAY,
    },
    "required": ["cards_found", "verdict", "heavier", "special_side",
                 "fake_warning", "red_cards", "yellow_cards"],
    "additionalProperties": False,
}

# The app writes the kid-facing line in code from the model's structured judgment,
# so grammar, point of view, and singular/plural are always correct.
CAP = {"red": "Red", "yellow": "Yellow"}


def _plural(n: int) -> str:
    return "thing" if n == 1 else "things"


def build_message(r: dict) -> str:
    v = r.get("verdict")
    nr, ny = len(r.get("red_cards", [])), len(r.get("yellow_cards", []))
    special = r.get("special_side") if r.get("special_side") in CAP else None
    heavier = r.get("heavier") if r.get("heavier") in CAP else None

    if v == "stop":
        side = CAP.get(special, "one")
        return random.choice([
            f"Wow! {side}'s thing might be something really special. Have a grown-up look first.",
            f"Ask a grown-up to look at {side}'s thing before you trade.",
            f"Wow! Have a grown-up check out {side}'s thing first.",
        ])

    if v == "uneven":
        pool = ["This one is maybe a little one-sided."]
        if nr != ny:
            pool.append(f"Are you sure you want to trade {nr} {_plural(nr)} for {ny} {_plural(ny)}?")
        if heavier:
            lighter = "yellow" if heavier == "red" else "red"
            pool.append(f"{CAP[lighter]} might need to add something to make this fair for {CAP[heavier]}.")
        if special:
            pool.append(f"{CAP[special]}'s thing is pretty special. Are you both okay with this?")
        return random.choice(pool)

    return random.choice([
        "That's a good deal if everyone feels okay about it!",
        "That's a great trade! All this stuff is really cool.",
        "You can both feel good about this one!",
    ])


def pick_face(r: dict) -> str:
    if r.get("verdict") == "stop":
        return "treasure"        # real-money item, show a grown-up
    if r.get("fake_warning"):
        return "confused"        # something looks off
    if r.get("verdict") == "uneven":
        return "uneven"
    return "fair"


class CheckRequest(BaseModel):
    red_image: str                # base64 (no data: prefix) — the red tile
    yellow_image: str             # the yellow tile
    red_media_type: str = "image/jpeg"
    yellow_media_type: str = "image/jpeg"


@app.post("/check")
def check(req: CheckRequest, request: Request):
    t0 = time.monotonic()
    ip = _client_ip(request)
    block = _limit_block(ip)
    if block == "budget":
        log.info("check: blocked daily budget (ip=%s)", ip)
        return _blocked_result("Buddy needs a little rest. Come back later!")
    if block == "user":
        log.info("check: blocked per-user cap (ip=%s)", ip)
        return _blocked_result("You've checked lots of trades today! Come back tomorrow.")
    log.info("check: start model=%s", MODEL)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "First photo = RED's stuff:"},
                    {"type": "image", "source": {"type": "base64",
                                                 "media_type": req.red_media_type,
                                                 "data": req.red_image}},
                    {"type": "text", "text": "Second photo = YELLOW's stuff:"},
                    {"type": "image", "source": {"type": "base64",
                                                 "media_type": req.yellow_media_type,
                                                 "data": req.yellow_image}},
                    {"type": "text", "text": "Judge this trade between Red and Yellow."},
                ],
            }],
        )
    except Exception as e:
        log.exception("check: vision call failed: %s", e)
        raise HTTPException(status_code=502, detail="vision call failed")

    text = next((b.text for b in response.content if b.type == "text"), "{}")
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        log.error("check: could not parse model output: %r", text[:500])
        raise HTTPException(status_code=502, detail="bad model output")

    # No real items on both sides -> don't invent a verdict, ask for another photo.
    valid = bool(result.get("cards_found")
                 and result.get("red_cards") and result.get("yellow_cards"))
    result["cards_found"] = valid
    if not valid:
        result["face"] = "confused"
        result["headline"] = "Hmm, I don't see anything to trade. Take another photo!"
        result["gem_alert"] = False
        result["gem_note"] = ""
    else:
        # The app writes the words from the structured judgment (see build_message).
        result["face"] = pick_face(result)
        result["headline"] = build_message(result)
        result["gem_alert"] = result.get("verdict") == "stop"
        if result["gem_alert"]:
            s = CAP.get(result.get("special_side"), "One")
            result["gem_note"] = f"{s}'s thing might be worth real money!"
        else:
            result["gem_note"] = ""

    u = response.usage
    log.info(
        "check: done verdict=%s face=%s heavier=%s special=%s fake=%s "
        "red=%d yellow=%d in_tokens=%s out_tokens=%s %.0fms",
        result.get("verdict"), result.get("face"), result.get("heavier"),
        result.get("special_side"), result.get("fake_warning"),
        len(result.get("red_cards", [])), len(result.get("yellow_cards", [])),
        u.input_tokens, u.output_tokens, (time.monotonic() - t0) * 1000,
    )
    _charge_day(ip, _cost(MODEL, u.input_tokens, u.output_tokens))
    _record(MODEL, result.get("verdict"), u.input_tokens, u.output_tokens)
    return result


@app.get("/stats")
def stats(key: str = ""):
    _require_key(key)
    with _lock:
        _roll_day()
        return {"model": MODEL, "totals": _stats, "recent": list(_recent),
                "today": {"date": _day["date"], "spend": _day["spend"],
                          "budget": DAILY_BUDGET_USD, "users": len(_day["ips"]),
                          "per_user_cap": PER_USER_DAILY}}


@app.post("/stats/reset")
def stats_reset(key: str = ""):
    _require_key(key)
    with _lock:
        _stats.update({"checks": 0, "in_tokens": 0, "out_tokens": 0, "cost": 0.0, "by_model": {}})
        _recent.clear()
        _save_stats()
    return {"ok": True}


@app.get("/dashboard")
def dashboard():
    return FileResponse("static/dashboard.html")


@app.get("/")
def index():
    return FileResponse("static/index.html")


app.mount("/", StaticFiles(directory="static"), name="static")
