"""Хранилище Cloudflare-аккаунтов (секреты — зашифрованы тем же ключом, что и AWS)."""
from dataclasses import dataclass

from ..storage import Storage
from .api import CloudflareAPI


@dataclass
class CfAccount:
    id: int
    user_id: int
    name: str
    email: str          # пусто для API Token
    secret: str         # API Token или Global API Key
    cf_account_id: str
    cf_account_name: str

    @property
    def auth_kind(self) -> str:
        return "Global API Key" if self.email else "API Token"

    def api(self) -> CloudflareAPI:
        if self.email:
            return CloudflareAPI(email=self.email, global_key=self.secret)
        return CloudflareAPI(token=self.secret)


class CloudflareStore:
    def __init__(self, storage: Storage):
        self._s = storage
        self._db = storage.db
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS cf_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                email TEXT NOT NULL DEFAULT '',
                secret_enc BLOB NOT NULL,
                cf_account_id TEXT NOT NULL DEFAULT '',
                cf_account_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS cf_active (
                user_id INTEGER PRIMARY KEY,
                account_id INTEGER NOT NULL
            );
            """
        )
        self._db.commit()

    def _row(self, r) -> CfAccount:
        return CfAccount(r["id"], r["user_id"], r["name"], r["email"], self._s.decrypt(r["secret_enc"]),
                         r["cf_account_id"], r["cf_account_name"])

    def add(self, user_id: int, name: str, email: str, secret: str, cf_id: str, cf_name: str) -> int:
        cur = self._db.execute(
            "INSERT INTO cf_accounts (user_id, name, email, secret_enc, cf_account_id, cf_account_name) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, name, email, self._s.encrypt(secret), cf_id, cf_name),
        )
        self._db.commit()
        if self.get_active(user_id) is None:
            self.set_active(user_id, cur.lastrowid)
        return cur.lastrowid

    def list(self, user_id: int) -> list[CfAccount]:
        rows = self._db.execute("SELECT * FROM cf_accounts WHERE user_id = ? ORDER BY id", (user_id,)).fetchall()
        return [self._row(r) for r in rows]

    def get(self, user_id: int, acc_id: int) -> CfAccount | None:
        r = self._db.execute("SELECT * FROM cf_accounts WHERE user_id = ? AND id = ?", (user_id, acc_id)).fetchone()
        return self._row(r) if r else None

    def delete(self, user_id: int, acc_id: int) -> None:
        self._db.execute("DELETE FROM cf_accounts WHERE user_id = ? AND id = ?", (user_id, acc_id))
        self._db.execute("DELETE FROM cf_active WHERE user_id = ? AND account_id = ?", (user_id, acc_id))
        self._db.commit()
        if self.get_active(user_id) is None:
            rest = self.list(user_id)
            if rest:
                self.set_active(user_id, rest[0].id)

    def set_active(self, user_id: int, acc_id: int) -> None:
        self._db.execute(
            "INSERT INTO cf_active (user_id, account_id) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET account_id = excluded.account_id",
            (user_id, acc_id),
        )
        self._db.commit()

    def get_active(self, user_id: int) -> CfAccount | None:
        r = self._db.execute(
            "SELECT a.* FROM cf_accounts a JOIN cf_active x ON x.account_id = a.id WHERE x.user_id = ?", (user_id,)
        ).fetchone()
        return self._row(r) if r else None

    def update_cf_account_id(self, acc_id: int, cf_id: str) -> None:
        self._db.execute("UPDATE cf_accounts SET cf_account_id = ? WHERE id = ?", (cf_id, acc_id))
        self._db.commit()
