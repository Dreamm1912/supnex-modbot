"""SQLite katmanı: sunucu ayarları, ticket'lar, uyarılar, log geçmişi."""
import os
import sqlite3
import time

from . import constants

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(_DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(_DATA_DIR, "modbot.db")

_CONN = sqlite3.connect(DB_PATH, check_same_thread=False)
_CONN.row_factory = sqlite3.Row


def _init() -> None:
    _CONN.executescript(
        """
        CREATE TABLE IF NOT EXISTS sunucu (
            guild_id INTEGER PRIMARY KEY,
            log_kanal_id INTEGER,
            mod_rol_id INTEGER,
            ticket_kategori_id INTEGER,
            destek_rol_id INTEGER,
            ticket_sayac INTEGER NOT NULL DEFAULT 0,
            ticket_baslik TEXT,
            ticket_aciklama TEXT,
            ticket_renk TEXT,
            ticket_resim TEXT,
            ticket_ikon TEXT,
            ticket_alt TEXT,
            ticket_otomatik_mesaj TEXT,
            ticket_konular TEXT,
            ping_destek INTEGER NOT NULL DEFAULT 1,
            ticket_panel_kanal_id INTEGER,
            ticket_panel_mesaj_id INTEGER,
            ticket_panel_embed TEXT
        );
        CREATE TABLE IF NOT EXISTS uyarilar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            sebep TEXT NOT NULL DEFAULT 'Sebep belirtilmedi',
            tarih INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tikets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            kanal_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            konu TEXT NOT NULL,
            durum TEXT NOT NULL DEFAULT 'acik',
            acilis INTEGER NOT NULL,
            kapanis INTEGER,
            transkript TEXT
        );
        CREATE TABLE IF NOT EXISTS guard (
            guild_id INTEGER PRIMARY KEY,
            aktif INTEGER NOT NULL DEFAULT 0,
            ban_korumasi INTEGER NOT NULL DEFAULT 1,
            kanal_korumasi INTEGER NOT NULL DEFAULT 1,
            rol_korumasi INTEGER NOT NULL DEFAULT 1,
            anti_raid INTEGER NOT NULL DEFAULT 1,
            beyaz_liste TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS log_gecmis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            tur TEXT NOT NULL,
            detay TEXT NOT NULL,
            zaman INTEGER NOT NULL
        );
        """
    )
    _CONN.commit()


_init()


def _migrate() -> None:
    for kolon in (
        "ticket_panel_kanal_id INTEGER",
        "ticket_panel_mesaj_id INTEGER",
        "ticket_panel_embed TEXT",
        "ses_kanal_id INTEGER",
    ):
        try:
            _CONN.execute(f"ALTER TABLE sunucu ADD COLUMN {kolon}")
        except sqlite3.OperationalError:
            pass
    _CONN.commit()


_migrate()


def _satir(tablo: str, guild_id: int):
    return _CONN.execute(f"SELECT * FROM {tablo} WHERE guild_id = ?", (guild_id,)).fetchone()


def _varsayilan_sunucu(guild_id: int) -> None:
    _CONN.execute(
        "INSERT OR IGNORE INTO sunucu (guild_id) VALUES (?)", (guild_id,)
    )
    _CONN.commit()


# --- sunucu ayarları ---
def sunucu(guild_id: int) -> sqlite3.Row:
    _varsayilan_sunucu(guild_id)
    return _satir("sunucu", guild_id)


def guncelle(guild_id: int, **alanlar) -> None:
    if not alanlar:
        return
    _varsayilan_sunucu(guild_id)
    atamalar = ", ".join(f"{k} = ?" for k in alanlar)
    degerler = list(alanlar.values()) + [guild_id]
    _CONN.execute(f"UPDATE sunucu SET {atamalar} WHERE guild_id = ?", degerler)
    _CONN.commit()


def konular(guild_id: int) -> list:
    satir = sunucu(guild_id)
    return constants.json_load(satir["ticket_konular"], constants.DEFAULT_KONULAR) or constants.DEFAULT_KONULAR


def sifirla(guild_id: int) -> None:
    guncelle(
        guild_id,
        ticket_baslik=constants.DEFAULT_TICKET_EMBED["baslik"],
        ticket_aciklama=constants.DEFAULT_TICKET_EMBED["aciklama"],
        ticket_renk=constants.DEFAULT_TICKET_EMBED["renk"],
        ticket_resim=constants.DEFAULT_TICKET_EMBED["resim"],
        ticket_ikon=constants.DEFAULT_TICKET_EMBED["ikon"],
        ticket_alt=constants.DEFAULT_TICKET_EMBED["alt"],
        ticket_otomatik_mesaj=constants.DEFAULT_OTOMATIK_MESAJ,
        ticket_konular=constants.json_dump(constants.DEFAULT_KONULAR),
        ping_destek=1,
    )


def ticket_embed_ayar(guild_id: int) -> dict:
    s = sunucu(guild_id)
    return {
        "baslik": s["ticket_baslik"],
        "aciklama": s["ticket_aciklama"],
        "renk": s["ticket_renk"],
        "resim": s["ticket_resim"],
        "ikon": s["ticket_ikon"],
        "alt": s["ticket_alt"],
    }


# --- uyarılar ---
def uyar_ekle(guild_id, user_id, moderator_id, sebep) -> int:
    cur = _CONN.execute(
        "INSERT INTO uyarilar (guild_id, user_id, moderator_id, sebep, tarih)"
        " VALUES (?, ?, ?, ?, ?)",
        (guild_id, user_id, moderator_id, sebep, int(time.time())),
    )
    _CONN.commit()
    return cur.lastrowid


def uyarilari_getir(guild_id, user_id) -> list:
    return _CONN.execute(
        "SELECT * FROM uyarilar WHERE guild_id = ? AND user_id = ? ORDER BY id DESC",
        (guild_id, user_id),
    ).fetchall()


def uyarlari_temizle(guild_id, user_id) -> int:
    cur = _CONN.execute(
        "DELETE FROM uyarilar WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    )
    _CONN.commit()
    return cur.rowcount


# --- ticket'lar ---
def ticket_ac(guild_id, kanal_id, user_id, konu) -> int:
    _varsayilan_sunucu(guild_id)
    sayac = _satir("sunucu", guild_id)["ticket_sayac"] + 1
    guncelle(guild_id, ticket_sayac=sayac)
    cur = _CONN.execute(
        "INSERT INTO tikets (guild_id, kanal_id, user_id, konu, acilis)"
        " VALUES (?, ?, ?, ?, ?)",
        (guild_id, kanal_id, user_id, konu, int(time.time())),
    )
    _CONN.commit()
    return sayac


def ticket_bul(kanal_id: int):
    return _CONN.execute(
        "SELECT * FROM tikets WHERE kanal_id = ? AND durum = 'acik'",
        (kanal_id,),
    ).fetchone()


def ticket_kapat(kanal_id: int, transkript_metni: str | None = None) -> None:
    _CONN.execute(
        "UPDATE tikets SET durum = 'kapali', kapanis = ?, transkript = ? WHERE kanal_id = ?",
        (int(time.time()), transkript_metni or "", kanal_id),
    )
    _CONN.commit()


def tikets_getir(guild_id: int, durum: str | None = None) -> list:
    if durum:
        return _CONN.execute(
            "SELECT * FROM tikets WHERE guild_id = ? AND durum = ? ORDER BY id DESC",
            (guild_id, durum),
        ).fetchall()
    return _CONN.execute(
        "SELECT * FROM tikets WHERE guild_id = ? ORDER BY id DESC", (guild_id,)
    ).fetchall()


# --- guard ---
def guard(guild_id: int) -> sqlite3.Row:
    _CONN.execute("INSERT OR IGNORE INTO guard (guild_id) VALUES (?)", (guild_id,))
    _CONN.commit()
    return _satir("guard", guild_id)


def guard_guncelle(guild_id: int, **alanlar) -> None:
    _CONN.execute("INSERT OR IGNORE INTO guard (guild_id) VALUES (?)", (guild_id,))
    atamalar = ", ".join(f"{k} = ?" for k in alanlar)
    degerler = list(alanlar.values()) + [guild_id]
    _CONN.execute(f"UPDATE guard SET {atamalar} WHERE guild_id = ?", degerler)
    _CONN.commit()


def guvenli_mi(guild_id: int, user_id: int) -> bool:
    """Guard'da yapılan işlemi yapan kişi güvenli mi (beyaz listede mi)?"""
    g = guard(guild_id)
    if user_id == constants_owner() or not g["aktif"]:
        return True
    liste = constants.json_load(g["beyaz_liste"], [])
    return user_id in liste


def constants_owner() -> int:
    import os
    return int(os.getenv("OWNER_ID", "0"))


# --- log geçmişi ---
def log_kaydet(guild_id: int, tur: str, detay: str) -> None:
    _CONN.execute(
        "INSERT INTO log_gecmis (guild_id, tur, detay, zaman) VALUES (?, ?, ?, ?)",
        (guild_id, tur, detay, int(time.time())),
    )
    _CONN.commit()


def log_gecmis_getir(guild_id: int, limit: int = 20) -> list:
    return _CONN.execute(
        "SELECT * FROM log_gecmis WHERE guild_id = ? ORDER BY id DESC LIMIT ?",
        (guild_id, limit),
    ).fetchall()