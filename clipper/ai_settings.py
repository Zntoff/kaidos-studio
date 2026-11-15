"""Each person's own connection to an AI provider: which provider, their API key for it, the models used
for each tier, the prices they pay, a spending budget, and a ledger of every call the app makes.

Everything lives in <data_dir>/settings.ai.json (owner-only permissions where the OS has them):

    {"provider": "openai",
     "providers": {"openai": {"api_key": "...", "base_url": "...", "models": {"fast": "...", ...},
                              "prices": {"fast": [in, out], ...}}},
     "api_key": "sk-ant-...",          # Anthropic key, as stored before multi-provider support
     "budget": {...}, "limits": {...}}

The provider catalog is config/providers.json, shared with the desktop app. A key in the environment
(ANTHROPIC_API_KEY, OPENAI_API_KEY...) still works as a fallback.

No provider returns the prepaid balance through the API, so "remaining" is the budget the person typed in
minus what this app has spent since then, priced with the figures in the catalog or the ones they entered."""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
from functools import lru_cache
from pathlib import Path

_lock = threading.RLock()
CATALOG_FILE = Path(__file__).resolve().parent.parent / "config" / "providers.json"
TIERS = ("fast", "standard", "superior")
GENERIC_TIER_NAMES = {"fast": "Rápido", "standard": "Estándar", "superior": "Superior"}

# Anthropic prices (USD per million tokens, input/output), kept for code that imports them.
PRICES = {"fast": (0.10, 0.50), "standard": (2.0, 10.0), "superior": (4.0, 20.0)}


@lru_cache(maxsize=1)
def catalog() -> list[dict]:
    return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))["providers"]


def meta(pid: str) -> dict | None:
    return next((p for p in catalog() if p["id"] == pid), None)


def _file(data_dir: Path) -> Path:
    return Path(data_dir) / "settings.ai.json"


def load(data_dir: Path) -> dict:
    try:
        return json.loads(_file(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(data_dir: Path, values: dict) -> None:
    with _lock:
        path = _file(data_dir)
        current = load(data_dir)
        current.update(values)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(current, indent=1), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(path)


def _save_provider(data_dir: Path, pid: str, **values) -> None:
    with _lock:
        data = load(data_dir)
        providers = data.get("providers") or {}
        entry = providers.get(pid) or {}
        entry.update(values)
        providers[pid] = entry
        save(data_dir, {"providers": providers})


# ---------- provider configuration ----------
def active_id(data_dir: Path) -> str:
    pid = load(data_dir).get("provider") or os.environ.get("CLIPPER_AI_PROVIDER") or "anthropic"
    return pid if meta(pid) else "anthropic"


def stored_key_for(data_dir: Path, pid: str) -> str | None:
    data = load(data_dir)
    key = ((data.get("providers") or {}).get(pid) or {}).get("api_key")
    if not key and pid == "anthropic":
        key = data.get("api_key")   # where the key lived before multi-provider support
    return key or None


def key_for(data_dir: Path, pid: str) -> tuple[str | None, str | None]:
    """The key and where it comes from: the panel beats the environment."""
    if key := stored_key_for(data_dir, pid):
        return key, "panel"
    env = (meta(pid) or {}).get("env")
    if env and os.environ.get(env):
        return os.environ[env], "env"
    return None, None


def stored_key(data_dir: Path) -> str | None:
    """The active provider's key (panel or environment)."""
    return key_for(data_dir, active_id(data_dir))[0]


def conf(data_dir: Path, pid: str | None = None) -> dict:
    """Catalog entry merged with what the person configured: url, models, prices, key."""
    pid = pid or active_id(data_dir)
    m = meta(pid) or meta("anthropic")
    stored = (load(data_dir).get("providers") or {}).get(pid) or {}
    models = {t: "" for t in TIERS}
    models.update(m.get("models") or {})
    if pid == "anthropic":   # the environment can pin Anthropic models, as before
        for t in TIERS:
            models[t] = os.environ.get(f"CLIPPER_MODEL_{t.upper()}") or models[t]
    models.update({t: v for t, v in (stored.get("models") or {}).items() if t in TIERS and v})
    prices = {t: list(v) for t, v in (m.get("prices") or {}).items()}
    prices.update({t: list(v) for t, v in (stored.get("prices") or {}).items() if t in TIERS and v is not None})
    key, source = key_for(data_dir, pid)
    return {**m, "base_url": (stored.get("base_url") or m.get("base_url") or "").rstrip("/"),
            "models": models, "prices": prices, "key": key, "key_source": source}


def credential_transport_error(base_url: str, key: str | None) -> str | None:
    from urllib.parse import urlsplit
    if not key:
        return None
    try:
        url = urlsplit(base_url)
        if url.scheme == "https" or url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1"):
            return None
    except ValueError:
        pass
    return "Use HTTPS to protect your API key. HTTP is allowed only for local loopback servers."


def missing(c: dict) -> str | None:
    """Why this provider cannot run a job yet, in words for the person; None when it can."""
    if c.get("needs_key") and not c.get("key"):
        return f"Falta la API key de {c['name']}. Añádela en Ajustes."
    if not c.get("base_url"):
        return f"Falta la dirección del servidor de {c['name']}. Complétala en Ajustes."
    if error := credential_transport_error(c["base_url"], c.get("key")):
        return error
    empty = [GENERIC_TIER_NAMES[t].lower() for t in TIERS if not c["models"].get(t)]
    if empty:
        return f"Elige los modelos de {c['name']} ({', '.join(empty)}) en Ajustes."
    return None


def apply(settings) -> None:
    """Copy the active provider into the running Settings (models per tier, key, endpoint)."""
    c = conf(settings.data_dir)
    settings.ai_provider, settings.ai_kind, settings.ai_name = c["id"], c["kind"], c["name"]
    settings.ai_base_url, settings.ai_dialect = c["base_url"], c.get("dialect") or ""
    settings.ai_max_tokens_field = c.get("max_tokens_field") or "max_tokens"
    settings.api_key = c["key"]
    settings.ai_missing = missing(c)
    settings.model_fast, settings.model_standard, settings.model_superior = (c["models"][t] or "" for t in TIERS)


def tier_names(c: dict) -> dict:
    return c.get("tier_names") or GENERIC_TIER_NAMES


def key_hint(key: str | None) -> str:
    """Enough to recognise a key, never enough to use it: long keys show 7 + 4 characters, short ones 3 + 2."""
    if not key:
        return ""
    if len(key) >= 24:
        return f"{key[:7]}…{key[-4:]}"
    return f"{key[:3]}…{key[-2:]}" if len(key) >= 12 else "•" * 6


def valid_key_format(key: str, pid: str = "anthropic") -> bool:
    if not key.isascii() or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in key) or len(key) < 8:
        return False
    prefix = (meta(pid) or {}).get("key_prefix")
    return not prefix or (key.startswith(prefix) and len(key) >= 30)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- ledger ----------
class Ledger:
    """One JSON line per model call, including retries and failed contracts (they cost too)."""

    def __init__(self, data_dir: Path, provider: str | None = None):
        self.path = Path(data_dir) / "usage.jsonl"
        self.provider = provider

    def add(self, rec: dict) -> None:
        rec = {"provider": self.provider, **rec} if self.provider else rec
        line = json.dumps({"ts": now_iso(), **rec}, ensure_ascii=False)
        with _lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def read(self, since: str | None = None) -> list[dict]:
        rows: list[dict] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return rows
        for line in lines:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not since or r.get("ts", "") >= since:
                rows.append(r)
        return rows


def _price_table(data_dir: Path) -> dict[tuple[str, str], tuple[float, float]]:
    """model id -> (input, output) USD per million tokens, from every configured provider."""
    table = {}
    for p in catalog():
        c = conf(data_dir, p["id"])
        for t in TIERS:
            model, price = c["models"].get(t), c["prices"].get(t)
            if model and price and (c["id"], model) not in table:
                table[c["id"], model] = (float(price[0]), float(price[1]))
    return table


def price_for(settings, model: str, provider: str | None = None) -> tuple[float, float] | None:
    """Price of a model, or None when nobody entered one (local models, a provider without prices)."""
    pid = provider or settings.ai_provider
    found = _price_table(settings.data_dir).get((pid, model))
    if found:
        return found
    low = (model or "").lower()
    if (provider is None or pid == "anthropic") and ("claude" in low or not low):
        return PRICES["fast" if "haiku" in low else "superior" if "opus" in low else "standard"]
    return None


def cost_of(settings, rec: dict, _cache: dict | None = None) -> float:
    model = rec.get("model", "")
    key = (rec.get("provider") or "anthropic", model)
    if _cache is not None and key in _cache:
        p = _cache[key]
    else:
        p = price_for(settings, model, key[0])
        if _cache is not None:
            _cache[key] = p
    if not p:
        return 0.0
    return (rec.get("input") or 0) * p[0] / 1e6 + (rec.get("output") or 0) * p[1] / 1e6


def summarize(settings, days: int = 30) -> dict:
    """Totals, per model, per day and the budget left, from the ledger."""
    data = load(settings.data_dir)
    ledger = Ledger(settings.data_dir)
    today = dt.datetime.now(dt.timezone.utc).date()
    first = today - dt.timedelta(days=max(1, days) - 1)
    rows = ledger.read(first.isoformat())
    cache: dict = {}
    by_model: dict[str, dict] = {}
    by_day = {(first + dt.timedelta(days=i)).isoformat(): {"day": (first + dt.timedelta(days=i)).isoformat(), "cost": 0.0, "calls": 0}
              for i in range(days)}
    totals = {"calls": 0, "input": 0, "output": 0, "cost": 0.0, "unpriced_calls": 0}
    for r in rows:
        c = cost_of(settings, r, cache)
        key = (r.get("provider") or "anthropic", r.get("model", ""))
        priced = cache.get(key) is not None
        m = by_model.setdefault(key, {"model": r.get("model", "?"), "provider": key[0],
                                                       "calls": 0, "input": 0, "output": 0, "cost": 0.0, "priced": priced})
        for d in (m, totals):
            d["calls"] += 1
            d["input"] += r.get("input") or 0
            d["output"] += r.get("output") or 0
            d["cost"] += c
        if not priced:
            totals["unpriced_calls"] += 1
        day = by_day.get(r.get("ts", "")[:10])
        if day:
            day["cost"] += c
            day["calls"] += 1
    budget = data.get("budget") or {}
    since = budget.get("since")
    spent = sum(cost_of(settings, r, cache) for r in ledger.read(since)) if budget.get("usd") is not None else None
    usd = budget.get("usd")
    active = conf(settings.data_dir)
    names = tier_names(active)
    return {
        "days": days, "totals": totals,
        "by_model": sorted(by_model.values(), key=lambda m: -m["cost"]),
        "by_day": list(by_day.values()),
        "budget": {"usd": usd, "since": since, "spent": spent,
                   "remaining": None if usd is None else usd - (spent or 0.0)},
        "provider": {"id": active["id"], "name": active["name"]},
        "prices": {t: {"name": names[t], "model": active["models"].get(t) or "",
                       "input": (active["prices"].get(t) or [None, None])[0], "output": (active["prices"].get(t) or [None, None])[1]}
                   for t in TIERS},
        "limits": data.get("limits"),
    }


def public_state(settings) -> dict:
    """What the Settings screen shows: the active provider and every provider's configuration (keys hidden)."""
    data = load(settings.data_dir)
    active = conf(settings.data_dir)
    providers = []
    for p in catalog():
        c = conf(settings.data_dir, p["id"])
        providers.append({k: c.get(k) for k in ("id", "name", "kind", "needs_key", "key_url", "note", "editable_url", "base_url", "models", "prices")}
                         | {"key_set": bool(c["key"]), "key_hint": key_hint(c["key"]), "source": c["key_source"],
                            "tier_names": tier_names(c), "missing": missing(c)})
    return {"provider": active["id"], "provider_name": active["name"], "providers": providers,
            "key_set": bool(active["key"]), "key_hint": key_hint(active["key"]), "source": active["key_source"],
            "ready": missing(active) is None, "missing": missing(active),
            "limits": data.get("limits") if active["id"] == "anthropic" else None,
            "budget": data.get("budget") or {"usd": None, "since": None}, "llm": settings.llm_provider}


def set_key(data_dir: Path, pid: str, key: str | None) -> None:
    if pid == "anthropic":   # keep the legacy field in sync so older builds still find it
        save(data_dir, {"api_key": key})
    _save_provider(data_dir, pid, api_key=key)


def set_provider(data_dir: Path, pid: str, base_url: str | None = None, models: dict | None = None,
                 prices: dict | None = None, activate: bool = True) -> None:
    values: dict = {}
    if base_url is not None:
        values["base_url"] = base_url.strip().rstrip("/")
    if models is not None:
        values["models"] = {t: (models.get(t) or "").strip() for t in TIERS}
    if prices is not None:
        values["prices"] = {t: [float(v[0]), float(v[1])] for t, v in prices.items() if t in TIERS and v is not None}
    if values:
        _save_provider(data_dir, pid, **values)
    if activate:
        save(data_dir, {"provider": pid})


# ---------- talking to providers ----------
class KeyError_(ValueError):
    """The key was rejected; the message is for the person."""


def verify(data_dir: Path, pid: str, key: str | None, ledger: Ledger | None = None) -> dict:
    """Prove a key works for a provider. Anthropic: a one-token call (it also returns the rate limits).
    OpenAI-compatible: list the models, which costs nothing and also feeds the model picker."""
    c = conf(data_dir, pid)
    if c["kind"] == "anthropic":
        res = verify_key(key, c["models"]["fast"] or "claude-haiku-5-5", ledger)
        return {**res, "models": None}
    models = list_models(c["base_url"], key, c["name"], c.get("dialect") or "")
    return {"ok": True, "warning": None if models else f"{c['name']} respondió, pero no devolvió modelos.", "limits": None, "models": models}


def list_models(base_url: str, key: str | None, name: str = "El proveedor", dialect: str = "") -> list[str]:
    import httpx

    if not base_url:
        raise KeyError_("Falta la dirección del servidor.")
    if error := credential_transport_error(base_url, key):
        raise KeyError_(error)
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    if dialect == "anthropic":
        headers = {"x-api-key": key or "", "anthropic-version": "2023-06-01"}
        base_url = base_url.rstrip("/") + ("" if base_url.rstrip("/").endswith("/v1") else "/v1")
    try:
        r = httpx.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=20.0)
    except httpx.HTTPError:
        raise KeyError_(f"No se pudo conectar con {name} en {base_url}. Revisa la dirección y tu conexión.")
    if r.status_code in (401, 403):
        raise KeyError_(f"{name} rechazó esta API key. Revisa que esté completa y que no esté revocada.")
    if r.status_code >= 400:
        raise KeyError_(f"{name} respondió {r.status_code}: provider request failed")
    try:
        items = r.json().get("data") or r.json().get("models") or []
    except ValueError:
        raise KeyError_(f"{name} no respondió con la API de OpenAI en {base_url}.")
    ids = [str(m.get("id") or m.get("name") or "") for m in items if isinstance(m, dict)]
    if dialect == "gemini":
        ids = [i.removeprefix("models/") for i in ids]
    return sorted({i for i in ids if i})


def verify_key(key: str, model: str, ledger: Ledger | None = None) -> dict:
    """Anthropic: make the smallest possible call (one output token) to prove the key works, and read
    the rate-limit headroom from the answer. Raises KeyError_ with a plain message when it does not."""
    import anthropic

    client = anthropic.Anthropic(api_key=key, max_retries=1, timeout=30.0)
    try:
        raw = client.messages.with_raw_response.create(model=model, max_tokens=1, messages=[{"role": "user", "content": "ping"}])
    except anthropic.AuthenticationError:
        raise KeyError_("Anthropic rechazó esta API key. Revisa que esté completa y que no esté revocada.")
    except anthropic.PermissionDeniedError:
        raise KeyError_("Esta API key no tiene permiso para usar los modelos. Revisa su espacio de trabajo en la consola.")
    except anthropic.BadRequestError as e:
        if "credit balance" in str(e).lower():
            return {"ok": True, "warning": "La key es válida, pero la cuenta no tiene crédito. Añade saldo en console.anthropic.com.", "limits": None}
        raise KeyError_(f"Anthropic respondió con un error: provider request failed")
    except anthropic.RateLimitError:
        return {"ok": True, "warning": "La key es válida, pero ahora mismo está en el límite de peticiones. Inténtalo en un minuto.", "limits": None}
    except anthropic.APIConnectionError:
        raise KeyError_("No se pudo conectar con Anthropic. Revisa tu conexión a internet.")
    except anthropic.APIStatusError as e:
        raise KeyError_(f"Anthropic respondió {e.status_code}: provider request failed")
    msg = raw.parse()
    if ledger:
        ledger.add({"agent": "prueba", "model": getattr(msg, "model", model),
                    "input": getattr(msg.usage, "input_tokens", 0), "output": getattr(msg.usage, "output_tokens", 0)})
    h = raw.headers
    limits = {}
    for name in ("requests", "tokens", "input-tokens", "output-tokens"):
        lim, rem = h.get(f"anthropic-ratelimit-{name}-limit"), h.get(f"anthropic-ratelimit-{name}-remaining")
        if lim is not None and rem is not None:
            limits[name.replace("-", "_")] = {"limit": int(lim), "remaining": int(rem), "reset": h.get(f"anthropic-ratelimit-{name}-reset")}
    return {"ok": True, "warning": None, "limits": {"checked_at": now_iso(), **limits} if limits else None}
