"""Türkçe embed yardımcıları."""
import discord

from . import constants

MIYAV = 0x00BFFF


def taban(title: str | None = None, description: str | None = None,
          color: discord.Color | int = MIYAV) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text=f"{constants.BRAND} v{constants.VERSION}")
    embed.timestamp = discord.utils.utcnow()
    return embed


def onay(metin: str) -> discord.Embed:
    return taban(description=f"✅ {metin}", color=0x2ECC71)


def hata(metin: str) -> discord.Embed:
    return taban(description=f"❌ {metin}", color=0xE74C3C)


def uyari_yaz(metin: str) -> discord.Embed:
    return taban(description=metin, color=0xF1C40F)


def anlik_sure(saniye: int) -> str:
    d = saniye // 86400
    h = (saniye % 86400) // 3600
    m = (saniye % 3600) // 60
    s = saniye % 60
    return f"{d}g {h}sa {m}dk {s}sn"