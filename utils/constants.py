"""Sabitler ve varsayılan ayarlar."""
import json

VERSION = "1.0"
BRAND = "Supnex Mod Bot"
BRAND_COLOR = 0x00BFFF

# Varsayılan ticket paneli gömülü mesajı ayarları
DEFAULT_TICKET_EMBED = {
    "baslik": "🎫 Destek Talebi",
    "aciklama": "Bir sorun mu var? Aşağıdan bir konu seç, ekibimiz sana yardımcı olsun.",
    "renk": "#00BFFF",
    "resim": "",
    "ikon": "",
    "alt": "Supnex Mod Bot • 7/24 aktif",
}

DEFAULT_KONULAR = ["Genel Destek", "Sorun Bildir", "Yetki / Rol Talebi", "Diğer"]

DEFAULT_OTOMATIK_MESAJ = "Hoş geldin {member}! Talebin {konu} kategorisinde alındı. Ekibimiz en kısa sürede burada olacak."


def json_dump(veri) -> str:
    return json.dumps(veri, ensure_ascii=False)


def json_load(metin: str, varsayilan=None):
    try:
        return json.loads(metin)
    except Exception:
        return varsayilan if varsayilan is not None else []