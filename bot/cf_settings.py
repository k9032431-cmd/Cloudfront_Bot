"""Настройки создаваемых CloudFront: значения по умолчанию, варианты и их перевод в конфиг AWS.

Чтобы добавить новую настройку — добавьте её в SETTINGS и DEFAULTS
и обработайте в apply_settings() / read_settings().
"""
from dataclasses import dataclass

# Managed-политики CloudFront (одинаковые во всех аккаунтах AWS)
CACHE_POLICIES = {
    "disabled": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",    # CachingDisabled
    "optimized": "658327ea-f89d-4fab-a63d-7e88639e58f6",   # CachingOptimized
    "origin": "83da9c7e-98b4-4e11-a168-04f0df8e2c65",      # UseOriginCacheControlHeaders
}
ORIGIN_REQUEST_POLICIES = {
    "allviewer": "216adef6-5c7f-47e4-b989-5492eafa07d3",   # AllViewer
    "nohost": "b689b0a8-53d0-40ab-baf2-68738e2966ac",      # AllViewerExceptHostHeader
    "cors": "59781a5b-3903-41f3-afcb-af62929ccde1",        # CORS-CustomOrigin
    "none": None,
}
METHODS = {
    "all": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
    "gho": ["GET", "HEAD", "OPTIONS"],
    "gh": ["GET", "HEAD"],
}


@dataclass(frozen=True)
class Setting:
    key: str
    title: str
    options: list[tuple[str, str]]  # (значение, подпись)

    def label(self, value: str) -> str:
        return dict(self.options).get(value, value)


SETTINGS: list[Setting] = [
    Setting("proto", "Origin protocol", [
        ("http-only", "HTTP only"), ("https-only", "HTTPS only"), ("match-viewer", "Match viewer"),
    ]),
    Setting("cache", "Cache policy", [
        ("disabled", "CachingDisabled"), ("optimized", "CachingOptimized"), ("origin", "UseOriginCacheControlHeaders"),
    ]),
    Setting("orp", "Origin request policy", [
        ("allviewer", "AllViewer"), ("nohost", "AllViewerExceptHostHeader"), ("cors", "CORS-CustomOrigin"), ("none", "Нет"),
    ]),
    Setting("viewer", "Viewer protocol policy", [
        ("redirect-to-https", "Redirect HTTP to HTTPS"), ("allow-all", "HTTP and HTTPS"), ("https-only", "HTTPS only"),
    ]),
    Setting("http", "HTTP versions", [
        ("http2and3", "HTTP/2 + HTTP/3"), ("http2", "HTTP/2"), ("http3", "HTTP/3"), ("http1.1", "HTTP/1.1"),
    ]),
    Setting("methods", "Allowed methods", [
        ("all", "Все (GET…DELETE)"), ("gho", "GET, HEAD, OPTIONS"), ("gh", "GET, HEAD"),
    ]),
    Setting("ipv6", "IPv6", [("on", "Включён"), ("off", "Выключен")]),
    Setting("price", "Price class", [
        ("PriceClass_All", "Все локации"), ("PriceClass_200", "Без самых дорогих"), ("PriceClass_100", "США, Европа"),
    ]),
]
SETTINGS_BY_KEY = {s.key: s for s in SETTINGS}

# Схема по умолчанию (как в инструкции): Other → Custom origin, HTTP only,
# CachingDisabled, AllViewer; остальное — как в консоли AWS + HTTP/3.
DEFAULTS: dict[str, str] = {
    "proto": "http-only",
    "cache": "disabled",
    "orp": "allviewer",
    "viewer": "redirect-to-https",
    "http": "http2and3",
    "methods": "all",
    "ipv6": "on",
    "price": "PriceClass_All",
}


def normalize(values: dict | None) -> dict[str, str]:
    """Дополняет недостающие ключи значениями по умолчанию и отбрасывает мусор."""
    out = dict(DEFAULTS)
    for k, v in (values or {}).items():
        if k in SETTINGS_BY_KEY and v in dict(SETTINGS_BY_KEY[k].options):
            out[k] = v
    return out


def summary(values: dict) -> str:
    values = normalize(values)
    return "\n".join(f"• {s.title}: <b>{s.label(values[s.key])}</b>" for s in SETTINGS)


def apply_settings(cfg: dict, values: dict) -> dict:
    """Применяет настройки к DistributionConfig (новому или существующему). Меняет cfg на месте."""
    v = normalize(values)
    cfg["HttpVersion"] = v["http"]
    cfg["IsIPV6Enabled"] = v["ipv6"] == "on"
    cfg["PriceClass"] = v["price"]

    for origin in cfg.get("Origins", {}).get("Items", []):
        custom = origin.get("CustomOriginConfig")
        if custom is not None:
            custom["OriginProtocolPolicy"] = v["proto"]

    beh = cfg["DefaultCacheBehavior"]
    beh["ViewerProtocolPolicy"] = v["viewer"]
    methods = METHODS[v["methods"]]
    beh["AllowedMethods"] = {
        "Quantity": len(methods),
        "Items": methods,
        "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]},
    }
    # Политики кэша несовместимы со старыми ForwardedValues/TTL — убираем их
    for legacy in ("ForwardedValues", "MinTTL", "DefaultTTL", "MaxTTL"):
        beh.pop(legacy, None)
    beh["CachePolicyId"] = CACHE_POLICIES[v["cache"]]
    orp = ORIGIN_REQUEST_POLICIES[v["orp"]]
    if orp:
        beh["OriginRequestPolicyId"] = orp
    else:
        beh.pop("OriginRequestPolicyId", None)
    return cfg


def read_settings(cfg: dict) -> dict[str, str]:
    """Читает текущие настройки из DistributionConfig существующей дистрибуции."""
    beh = cfg.get("DefaultCacheBehavior", {})
    origins = cfg.get("Origins", {}).get("Items", [])
    custom = origins[0].get("CustomOriginConfig", {}) if origins else {}
    allowed = sorted(beh.get("AllowedMethods", {}).get("Items", []))
    rev = lambda d, val: next((k for k, x in d.items() if x == val), None)  # noqa: E731
    return normalize({
        "proto": custom.get("OriginProtocolPolicy"),
        "cache": rev(CACHE_POLICIES, beh.get("CachePolicyId")),
        "orp": rev(ORIGIN_REQUEST_POLICIES, beh.get("OriginRequestPolicyId")),
        "viewer": beh.get("ViewerProtocolPolicy"),
        "http": cfg.get("HttpVersion"),
        "methods": rev({k: sorted(m) for k, m in METHODS.items()}, allowed),
        "ipv6": "on" if cfg.get("IsIPV6Enabled") else "off",
        "price": cfg.get("PriceClass"),
    })
