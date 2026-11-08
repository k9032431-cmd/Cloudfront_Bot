"""Работа с AWS: проверка ключей и управление CloudFront-дистрибуциями."""
import asyncio
import time
from dataclasses import dataclass

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from . import cf_settings
from .storage import Account

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
    arn: str = ""


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
        arn=d.get("ARN", ""),
    )


def _build_config(name: str, origin_domain: str, settings: dict) -> dict:
    """Origin type: Other → Custom origin. Остальное — из settings (см. bot/cf_settings.py)."""
    origin_id = origin_domain[:128]
    cfg = {
        "CallerReference": f"tgbot-{int(time.time() * 1000)}",
        "Comment": name[:128],
        "Enabled": True,
        "DefaultRootObject": "",
        "Origins": {
            "Quantity": 1,
            "Items": [{
                "Id": origin_id,
                "DomainName": origin_domain,
                "OriginPath": "",
                "ConnectionAttempts": 3,
                "ConnectionTimeout": 10,
                "CustomOriginConfig": {
                    "HTTPPort": 80,
                    "HTTPSPort": 443,
                    "OriginProtocolPolicy": "http-only",
                    "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]},
                    "OriginReadTimeout": 30,
                    "OriginKeepaliveTimeout": 5,
                },
            }],
        },
        "DefaultCacheBehavior": {"TargetOriginId": origin_id, "Compress": True},
    }
    return cf_settings.apply_settings(cfg, settings)


def _create_distribution(account: Account, name: str, origin_domain: str, settings: dict) -> DistributionInfo:
    resp = _cf(account).create_distribution_with_tags(
        DistributionConfigWithTags={
            "DistributionConfig": _build_config(name, origin_domain, settings),
            "Tags": {"Items": [{"Key": "Name", "Value": name[:256]}]},
        }
    )
    return _to_info(resp["Distribution"], resp.get("ETag", ""))


async def create_distribution(account: Account, name: str, origin_domain: str, settings: dict) -> DistributionInfo:
    return await asyncio.to_thread(_wrap, _create_distribution, account, name, origin_domain, settings)


def _get_settings(account: Account, dist_id: str) -> dict:
    cfg = _cf(account).get_distribution_config(Id=dist_id)["DistributionConfig"]
    return cf_settings.read_settings(cfg)


async def get_settings(account: Account, dist_id: str) -> dict:
    """Текущие настройки существующей дистрибуции."""
    return await asyncio.to_thread(_wrap, _get_settings, account, dist_id)


def _update_settings(account: Account, dist_id: str, settings: dict) -> None:
    client = _cf(account)
    resp = client.get_distribution_config(Id=dist_id)
    cfg = cf_settings.apply_settings(resp["DistributionConfig"], settings)
    client.update_distribution(Id=dist_id, IfMatch=resp["ETag"], DistributionConfig=cfg)


async def update_settings(account: Account, dist_id: str, settings: dict) -> None:
    """Применяет настройки к уже созданной дистрибуции."""
    await asyncio.to_thread(_wrap, _update_settings, account, dist_id, settings)


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
