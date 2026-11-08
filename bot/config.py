import logging
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    bot_token: str
    allowed_users: frozenset[int]
    encryption_key: bytes
    db_path: Path
    disabled_modules: frozenset[str] = frozenset()


def _load_encryption_key(db_dir: Path) -> bytes:
    key = os.getenv("ENCRYPTION_KEY", "").strip()
    if key:
        return key.encode()
    key_file = db_dir / "fernet.key"
    if key_file.exists():
        return key_file.read_bytes().strip()
    db_dir.mkdir(parents=True, exist_ok=True)
    new_key = Fernet.generate_key()
    key_file.write_bytes(new_key)
    os.chmod(key_file, 0o600)
    log.warning("ENCRYPTION_KEY не задан — создан новый ключ в %s. Не теряйте его!", key_file)
    return new_key


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN не задан. Скопируйте .env.example в .env и заполните его.")
    allowed = frozenset(
        int(x) for x in os.getenv("ALLOWED_USERS", "").replace(" ", "").split(",") if x
    )
    db_path = Path(os.getenv("DB_PATH", "data/bot.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return Config(
        bot_token=token,
        allowed_users=allowed,
        encryption_key=_load_encryption_key(db_path.parent),
        db_path=db_path,
        disabled_modules=frozenset(
            x.strip() for x in os.getenv("DISABLED_MODULES", "").split(",") if x.strip()
        ),
    )
