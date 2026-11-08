"""SQLite-хранилище AWS-аккаунтов. Секретные ключи хранятся зашифрованными (Fernet)."""
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
            CREATE TABLE IF NOT EXISTS active_account (
                user_id INTEGER PRIMARY KEY,
                account_id INTEGER NOT NULL
            );
            """
        )
        self._db.commit()

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
