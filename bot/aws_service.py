"""Работа с AWS: проверка ключей и управление CloudFront-дистрибуциями."""
import asyncio
import time
from dataclasses import dataclass

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from .storage import Account

# Managed-политики CloudFront (одинаковые во всех аккаунтах AWS)
CACHE_POLICY_CACHING_DISABLED = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
CACHE_POLICY_CACHING_OPTIMIZED = "658327ea-f89d-4fab-a63d-7e88639e58f6"
ORIGIN_REQUEST_POLICY_ALL_VIEWER = "216adef6-5c7f-47e4-b989-5492eafa07d3"

_BOTO_CFG = BotoConfig(retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=10, read_timeout=30)


class AwsError(Exception):
    pass


@dataclass
class DistributionInfo:
    id: str
    domain: str
    status: str
    enabled: bool
    origin: str
    comment: str
    etag: str = ""


def _session(access_key: str, secret: str, region: str = "us-east-1") -> boto3.Session:
    return boto3.Session(aws_access_key_id=access_key, aws_secret_access_key=secret, region_name=region)


def _cf(account: Account):
    # CloudFront — глобальный сервис, его API живёт в us-east-1
    return _session(account.access_key_id, account.secret_access_key).client("cloudfront", config=_BOTO_CFG)


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ClientError as e:
        err = e.response.get("Error", {})
        raise AwsError(f"{err.get('Code', 'Error')}: {err.get('Message', str(e))}") from e
    except BotoCoreError as e:
        raise AwsError(str(e)) from e


# ---------- Проверка ключей ----------

def _verify_credentials(access_key: str, secret: str) -> str:
    sts = _session(access_key, secret).client("sts", config=_BOTO_CFG)
    ident = sts.get_caller_identity()
    return ident["Account"]


async def verify_credentials(access_key: str, secret: str) -> str:
    """Возвращает ID AWS-аккаунта, если ключи рабочие."""
    return await asyncio.to_thread(_wrap, _verify_credentials, access_key, secret)


# ---------- CloudFront ----------

def _to_info(d: dict, etag: str = "") -> DistributionInfo:
    cfg = d.get("DistributionConfig", d)
    origins = cfg.get("Origins", {}).get("Items", [])
    return DistributionInfo(
        id=d["Id"],
        domain=d["DomainName"],
        status=d["Status"],
        enabled=cfg.get("Enabled", d.get("Enabled", False)),
        origin=origins[0]["DomainName"] if origins else "-",
        comment=cfg.get("Comment", d.get("Comment", "")),
        etag=etag,
    )


def _create_distribution(account: Account, origin_domain: str, origin_protocol: str, caching: bool) -> DistributionInfo:
    origin_id = f"origin-{origin_domain}"[:128]
    config = {
        "CallerReference": f"tgbot-{int(time.time() * 1000)}",
        "Comment": f"Created by bot: {origin_domain}"[:128],
        "Enabled": True,
        "PriceClass": "PriceClass_All",
        "HttpVersion": "http2and3",
        "IsIPV6Enabled": True,
        "Origins": {
            "Quantity": 1,
            "Items": [{
                "Id": origin_id,
                "DomainName": origin_domain,
                "CustomOriginConfig": {
                    "HTTPPort": 80,
                    "HTTPSPort": 443,
                    "OriginProtocolPolicy": origin_protocol,  # http-only | https-only | match-viewer
                    "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]},
                    "OriginReadTimeout": 30,
                    "OriginKeepaliveTimeout": 5,
                },
            }],
        },
        "DefaultCacheBehavior": {
            "TargetOriginId": origin_id,
            "ViewerProtocolPolicy": "allow-all",
            "AllowedMethods": {
                "Quantity": 7,
                "Items": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
                "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]},
            },
            "Compress": True,
            "CachePolicyId": CACHE_POLICY_CACHING_OPTIMIZED if caching else CACHE_POLICY_CACHING_DISABLED,
            "OriginRequestPolicyId": ORIGIN_REQUEST_POLICY_ALL_VIEWER,
        },
    }
    resp = _cf(account).create_distribution(DistributionConfig=config)
    return _to_info(resp["Distribution"], resp.get("ETag", ""))


async def create_distribution(account: Account, origin_domain: str, origin_protocol: str = "match-viewer",
                              caching: bool = False) -> DistributionInfo:
    return await asyncio.to_thread(_wrap, _create_distribution, account, origin_domain, origin_protocol, caching)


def _list_distributions(account: Account) -> list[DistributionInfo]:
    client = _cf(account)
    result = []
    for page in client.get_paginator("list_distributions").paginate():
        for item in page.get("DistributionList", {}).get("Items", []) or []:
            result.append(_to_info(item))
    return result


async def list_distributions(account: Account) -> list[DistributionInfo]:
    return await asyncio.to_thread(_wrap, _list_distributions, account)


def _get_distribution(account: Account, dist_id: str) -> DistributionInfo:
    resp = _cf(account).get_distribution(Id=dist_id)
    return _to_info(resp["Distribution"], resp["ETag"])


async def get_distribution(account: Account, dist_id: str) -> DistributionInfo:
    return await asyncio.to_thread(_wrap, _get_distribution, account, dist_id)


def _set_enabled(account: Account, dist_id: str, enabled: bool) -> None:
    client = _cf(account)
    resp = client.get_distribution_config(Id=dist_id)
    cfg = resp["DistributionConfig"]
    cfg["Enabled"] = enabled
    client.update_distribution(Id=dist_id, IfMatch=resp["ETag"], DistributionConfig=cfg)


async def set_enabled(account: Account, dist_id: str, enabled: bool) -> None:
    await asyncio.to_thread(_wrap, _set_enabled, account, dist_id, enabled)


def _delete_distribution(account: Account, dist_id: str) -> None:
    client = _cf(account)
    resp = client.get_distribution(Id=dist_id)
    dist = resp["Distribution"]
    if dist["DistributionConfig"]["Enabled"] or dist["Status"] != "Deployed":
        raise AwsError("Сначала выключите дистрибуцию и дождитесь статуса Deployed (обычно 5–15 минут).")
    client.delete_distribution(Id=dist_id, IfMatch=resp["ETag"])


async def delete_distribution(account: Account, dist_id: str) -> None:
    await asyncio.to_thread(_wrap, _delete_distribution, account, dist_id)
