"""SQLite-хранилище AWS-аккаунтов. Секретные ключи хранятся зашифрованными (Fernet)."""
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet


@dataclass
class Account:
    id: int
    user_id: int
    name: str
    access_key_id: str
    secret_access_key: str
    region: str
    aws_account_id: str

    @property
    def masked_key(self) -> str:
        return f"{self.access_key_id[:4]}…{self.access_key_id[-4:]}"


class Storage:
    def __init__(self, db_path: Path, encryption_key: bytes):
        self._fernet = Fernet(encryption_key)
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                access_key_id TEXT NOT NULL,
                secret_enc BLOB NOT NULL,
                region TEXT NOT NULL DEFAULT 'us-east-1',
                aws_account_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                added_by INTEGER,
                added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS active_account (
                user_id INTEGER PRIMARY KEY,
                account_id INTEGER NOT NULL
            );
            """
        )
        self._db.commit()

    def encrypt(self, text: str) -> bytes:
        """Шифрует секрет (для модулей, которым нужно хранить свои ключи)."""
        return self._fernet.encrypt(text.encode())

    def decrypt(self, blob: bytes) -> str:
        return self._fernet.decrypt(blob).decode()

    @property
    def db(self) -> sqlite3.Connection:
        """Соединение с БД — модули могут создавать в нём свои таблицы."""
        return self._db

    def _row_to_account(self, row: sqlite3.Row) -> Account:
        return Account(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            access_key_id=row["access_key_id"],
            secret_access_key=self._fernet.decrypt(row["secret_enc"]).decode(),
            region=row["region"],
            aws_account_id=row["aws_account_id"],
        )

    def add_account(
        self, user_id: int, name: str, access_key_id: str, secret: str,
        region: str, aws_account_id: str,
    ) -> int:
        cur = self._db.execute(
            "INSERT INTO accounts (user_id, name, access_key_id, secret_enc, region, aws_account_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, name, access_key_id, self._fernet.encrypt(secret.encode()), region, aws_account_id),
        )
        self._db.commit()
        account_id = cur.lastrowid
        # Первый добавленный аккаунт сразу становится активным
        if self.get_active(user_id) is None:
            self.set_active(user_id, account_id)
        return account_id

    def list_accounts(self, user_id: int) -> list[Account]:
        rows = self._db.execute(
            "SELECT * FROM accounts WHERE user_id = ? ORDER BY id", (user_id,)
        ).fetchall()
        return [self._row_to_account(r) for r in rows]

    def get_account(self, user_id: int, account_id: int) -> Account | None:
        row = self._db.execute(
            "SELECT * FROM accounts WHERE user_id = ? AND id = ?", (user_id, account_id)
        ).fetchone()
        return self._row_to_account(row) if row else None

    def delete_account(self, user_id: int, account_id: int) -> None:
        self._db.execute("DELETE FROM accounts WHERE user_id = ? AND id = ?", (user_id, account_id))
        self._db.execute(
            "DELETE FROM active_account WHERE user_id = ? AND account_id = ?", (user_id, account_id)
        )
        self._db.commit()
        if self.get_active(user_id) is None:
            remaining = self.list_accounts(user_id)
            if remaining:
                self.set_active(user_id, remaining[0].id)

    def set_active(self, user_id: int, account_id: int) -> None:
        self._db.execute(
            "INSERT INTO active_account (user_id, account_id) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET account_id = excluded.account_id",
            (user_id, account_id),
        )
        self._db.commit()

    def get_active(self, user_id: int) -> Account | None:
        row = self._db.execute(
            "SELECT a.* FROM accounts a JOIN active_account aa ON aa.account_id = a.id "
            "WHERE aa.user_id = ?",
            (user_id,),
        ).fetchone()
        return self._row_to_account(row) if row else None

    # ---------- Шаблон настроек CloudFront ----------

    def get_settings(self, user_id: int) -> dict:
        from .cf_settings import normalize
        row = self._db.execute("SELECT data FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
        return normalize(json.loads(row["data"]) if row else None)

    def save_settings(self, user_id: int, data: dict | None) -> None:
        """Сохраняет шаблон настроек; None — сброс к схеме по умолчанию."""
        if data is None:
            self._db.execute("DELETE FROM user_settings WHERE user_id = ?", (user_id,))
        else:
            self._db.execute(
                "INSERT INTO user_settings (user_id, data) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET data = excluded.data",
                (user_id, json.dumps(data)),
            )
        self._db.commit()

    # ---------- Пользователи с доступом ----------

    def is_user(self, user_id: int) -> bool:
        return self._db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)).fetchone() is not None

    def add_user(self, user_id: int, added_by: int, name: str = "") -> bool:
        """Возвращает False, если пользователь уже был."""
        cur = self._db.execute(
            "INSERT OR IGNORE INTO users (user_id, name, added_by) VALUES (?, ?, ?)", (user_id, name, added_by)
        )
        self._db.commit()
        return cur.rowcount > 0

    def remove_user(self, user_id: int) -> None:
        self._db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        self._db.commit()

    def update_user_name(self, user_id: int, name: str) -> None:
        self._db.execute("UPDATE users SET name = ? WHERE user_id = ? AND name != ?", (name, user_id, name))
        self._db.commit()

    def list_users(self) -> list[dict]:
        rows = self._db.execute("SELECT user_id, name, added_at FROM users ORDER BY added_at").fetchall()
        return [dict(r) for r in rows]
