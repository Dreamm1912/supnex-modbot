"""Sade ve sağlam ticket sistemi — Marpel tarzı panel + konu seçici.

Tek kurulum: /talep-kur ile kategori, panel kanalı ve log kanalı otomatik kurulur.
Panel kalıcıdır (persistent view) — bot yeniden başlasa bile butonlar çalışır.
"""
import asyncio
import io
import time

import discord
from discord import app_commands
from discord.ext import commands

from utils import constants, db, embeds


def _slug(metin: str) -> str:
    harfler = {"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u"}
    s = "".join(harfler.get(c, c) for c in metin.lower())
    s = "".join(c if c.isalnum() else "-" for c in s)
    return s.strip("-").strip() or "talep"


def _staff_mi(interaction: discord.Interaction) -> bool:
    s = db.sunucu(interaction.guild.id)
    if s["destek_rol_id"]:
        rol = interaction.guild.get_role(s["destek_rol_id"])
        if rol and rol in interaction.user.roles:
            return True
    return interaction.user.guild_permissions.manage_channels or interaction.user.id == db.constants_owner()


def _panel_embed(guild_id: int) -> discord.Embed:
    a = db.ticket_embed_ayar(guild_id)
    renk = 0x00BFFF
    try:
        renk = int((a["renk"] or "00BFFF").lstrip("#"), 16)
    except ValueError:
        renk = 0x00BFFF
    embed = embeds.taban(
        title=a["baslik"] or "Destek Talebi",
        description=a["aciklama"] or "Aşağıdaki menüden talep konunu seç, sana özel kanal açılsın!",
        color=renk,
    )
    if a["ikon"]:
        embed.set_thumbnail(url=a["ikon"])
    if a["resim"]:
        embed.set_image(url=a["resim"])
    embed.set_footer(text=a["alt"] or f"{constants.BRAND} • 24/7 destek")
    return embed


# --- panel (kalıcı) ---
class KonuSeciciView(discord.ui.View):
    def __init__(self, bot: commands.Bot, konular: list[str] | None = None) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(KonuSecici(bot, konular or constants.DEFAULT_KONULAR))


class KonuSecici(discord.ui.Select):
    def __init__(self, bot: commands.Bot, konular: list[str]) -> None:
        self.bot = bot
        secenekler = [
            discord.SelectOption(label=k[:80], value=k[:100], description="Talep açmak için seç")
            for k in konular[:25]
        ]
        if not secenekler:
            secenekler = [discord.SelectOption(label="Genel Destek", value="Genel Destek")]
        super().__init__(
            custom_id="supnex_talep_konu",
            placeholder="Talep konunu seç...",
            min_values=1,
            max_values=1,
            options=secenekler,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        konu = self.values[0]
        guild = interaction.guild
        uye = interaction.user

        s = db.sunucu(guild.id)
        acik = db.tikets_getir(guild.id, "acik")
        mevcut = [t for t in acik if t["user_id"] == uye.id and t["kanal_id"]]
        if mevcut:
            kanal = guild.get_channel(mevcut[0]["kanal_id"])
            if kanal:
                await interaction.response.send_message(
                    embed=embeds.hata(f"Zaten açık talebin var: {kanal.mention}"), ephemeral=True
                )
                return
            await interaction.response.send_message(
                embed=embeds.hata("Zaten açık talebin var. Lütfen önce onu kapat."), ephemeral=True
            )
            return

        kategori = guild.get_channel(s["ticket_kategori_id"]) if s["ticket_kategori_id"] else None
        if not kategori:
            try:
                kategori = await _kategori_kur(guild, s["destek_rol_id"])
                db.guncelle(guild.id, ticket_kategori_id=kategori.id)
            except discord.Forbidden:
                kategori = None

        destek_rol = guild.get_role(s["destek_rol_id"]) if s["destek_rol_id"] else None
        sayac = db.ticket_ac(guild.id, 0, uye.id, konu)

        yetkiler = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            uye: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_messages=True, read_message_history=True),
        }
        if destek_rol:
            yetkiler[destek_rol] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True)

        try:
            kanal = await guild.create_text_channel(
                name=f"talep-{sayac}-{_slug(konu)[:18]}",
                category=kategori,
                overwrites=yetkiler,
                topic=f"{konu} • {uye} ({uye.id})",
            )
        except discord.Forbidden:
            db._CONN.execute(
                "DELETE FROM tikets WHERE guild_id = ? AND user_id = ? AND kanal_id = 0 "
                "AND id = (SELECT MAX(id) FROM tikets WHERE guild_id = ? AND user_id = ? AND kanal_id = 0)",
                (guild.id, uye.id, guild.id, uye.id),
            )
            s = db.sunucu(guild.id)
            db.guncelle(guild.id, ticket_sayac=max(0, (s["ticket_sayac"] or 0) - 1))
            await interaction.response.send_message(
                embed=embeds.hata("Talep kanalı oluşturulamadı (yetki sorunu). Kurulumu kontrol et: `/talep-kur`"),
                ephemeral=True,
            )
            return

        db._CONN.execute(
            "UPDATE tikets SET kanal_id = ? WHERE guild_id = ? AND user_id = ? AND kanal_id = 0",
            (kanal.id, guild.id, uye.id),
        )
        db._CONN.commit()

        await self._hosgeldin(guild, kanal, uye, konu, sayac, destek_rol, bool(s["ping_destek"]))
        await interaction.response.send_message(
            embed=embeds.onay(f"Talebin açıldı: {kanal.mention}"), ephemeral=True
        )

        db.log_kaydet(guild.id, "talep_ac", f"{uye.id} konu:{konu} kanal:{kanal.id}")
        log_kanal = interaction.client.get_channel(s["log_kanal_id"]) if s["log_kanal_id"] else None
        if log_kanal:
            try:
                await log_kanal.send(embed=embeds.taban(
                    title="🎫 Talep açıldı",
                    description=f"**Konu:** {konu}\n**Açan:** {uye.mention} (`{uye.id}`)\n"
                                f"**Kanal:** <#{kanal.id}>",
                    color=0x2ECC71,
                ))
            except discord.HTTPException:
                pass

    @staticmethod
    async def _hosgeldin(guild: discord.Guild, kanal: discord.TextChannel, uye: discord.Member,
                         konu: str, sayac: int, destek_rol: discord.Role | None, ping: bool) -> None:
        s = db.sunucu(guild.id)
        mesaj = s["ticket_otomatik_mesaj"] or constants.DEFAULT_OTOMATIK_MESAJ
        renk = 0x00BFFF
        try:
            renk = int((s["ticket_renk"] or "00BFFF").lstrip("#"), 16)
        except ValueError:
            renk = 0x00BFFF
        embed = embeds.taban(
            title=f"🎫 {konu} — Talep #{sayac}",
            description=mesaj.format(member=uye.mention, konu=konu),
            color=renk,
        )
        if destek_rol:
            embed.add_field(name="Yetkili", value=destek_rol.mention, inline=False)
        embed.add_field(name="Açan", value=uye.mention, inline=True)
        embed.add_field(name="Talep No", value=f"`{sayac}`", inline=True)
        await kanal.send(embed=embed, view=TalepYonetView(uye.id))
        if destek_rol and ping:
            await kanal.send(destek_rol.mention, delete_after=2)


# --- talep kanalı butonları (kalıcı) ---
class TalepYonetView(discord.ui.View):
    def __init__(self, sahip_id: int | None = None) -> None:
        super().__init__(timeout=None)
        self.sahip_id = sahip_id
        self.add_item(TalepKapatButon())
        self.add_item(TalepTranskriptButon())


class TalepKapatButon(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Talebi Kapat", style=discord.ButtonStyle.danger, custom_id="supnex_talep_kapat")

    async def callback(self, interaction: discord.Interaction) -> None:
        kayit = db.ticket_bul(interaction.channel_id)
        if not kayit:
            await interaction.response.send_message(
                embed=embeds.hata("Bu kanal aktif bir talep değil."), ephemeral=True
            )
            return
        sahip = interaction.user.id == kayit["user_id"]
        if not (sahip or _staff_mi(interaction)):
            await interaction.response.send_message(
                embed=embeds.hata("Yalnızca talep sahibi veya yetkililer kapatabilir."), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=embeds.uyari_yaz("Talebi kapatmak istiyor musun? Kapanırken transkript log kanalına kaydedilir."),
            view=TalepKapatmaOnay(), ephemeral=True,
        )


class TalepTranskriptButon(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Transkript", style=discord.ButtonStyle.secondary, custom_id="supnex_talep_transkript")

    async def callback(self, interaction: discord.Interaction) -> None:
        if not _staff_mi(interaction):
            await interaction.response.send_message(
                embed=embeds.hata("Bu butonu yalnızca yetkililer kullanabilir."), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        t = await _transkript_al(interaction.channel)
        if not t:
            await interaction.followup.send(embed=embeds.hata("Transkript alınamadı."), ephemeral=True)
            return
        s = db.sunucu(interaction.guild.id)
        if s["log_kanal_id"]:
            await _transkript_at(interaction.client, s["log_kanal_id"], interaction.channel.name, t)
        await interaction.followup.send(embed=embeds.onay("Transkript log kanalına atıldı."), ephemeral=True)


class TalepKapatmaOnay(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=120)

    @discord.ui.button(label="Evet, kapat", style=discord.ButtonStyle.danger)
    async def evet(self, interaction: discord.Interaction, _) -> None:
        await interaction.response.defer(ephemeral=True)
        kanal = interaction.channel
        kayit = db.ticket_bul(kanal.id)
        t = None
        if kayit:
            try:
                t = await _transkript_al(kanal)
            except Exception:
                t = None
            s = db.sunucu(interaction.guild.id)
            if t and s["log_kanal_id"]:
                await _transkript_at(interaction.client, s["log_kanal_id"], kanal.name, t)
            db.ticket_kapat(kanal.id, t)
            db.log_kaydet(interaction.guild.id, "talep_kapat", f"{kanal.id} kapat:{interaction.user.id}")
            log_kanal = interaction.client.get_channel(s["log_kanal_id"]) if s["log_kanal_id"] else None
            if log_kanal:
                try:
                    await log_kanal.send(embed=embeds.taban(
                        title="🎫 Talep kapatıldı",
                        description=f"**Kanal:** {kanal.name}\n**Kapatan:** {interaction.user.mention}",
                        color=0xE74C3C,
                    ))
                except discord.HTTPException:
                    pass
        await interaction.followup.send(embed=embeds.onay("Talep kapatılıyor..."), ephemeral=True)
        await asyncio.sleep(3)
        try:
            await kanal.delete(reason="Talep kapatıldı.")
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Vazgeç", style=discord.ButtonStyle.secondary)
    async def vazgec(self, interaction: discord.Interaction, _) -> None:
        await interaction.response.edit_message(content="İşlem iptal edildi.", embed=None, view=None)


# --- transkript ---
async def _transkript_al(kanal: discord.TextChannel) -> str | None:
    try:
        mesajlar = [m async for m in kanal.history(limit=5000, oldest_first=True)]
    except discord.HTTPException:
        return None
    if not mesajlar:
        return None
    satirlar = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>body{font-family:Segoe UI;background:#1e1e1e;color:#eee;margin:0;padding:20px}"
        ".m{margin:8px 0;padding:8px;border-radius:6px;background:#2a2a2a}"
        "img{max-width:320px;border-radius:6px}.a{color:#7289da;font-weight:700}"
        ".t{color:#999;font-size:.8em}</style></head><body>",
        f"<h2>Transkript: {kanal.name} ({kanal.guild.name})</h2>",
    ]
    for m in mesajlar:
        icerik = (m.content or "").replace("<", "&lt;").replace(">", "&gt;")
        ekstra = ""
        if m.embeds:
            ekstra += " [embed]"
        if m.attachments:
            for e in m.attachments:
                ekstra += f'<br><img src="{e.url}">'
        satirlar.append(
            f'<div class="m"><span class="a">{m.author.display_name}</span> '
            f'<span class="t">#{m.author.id}</span><br>{icerik}{ekstra}</div>'
        )
    satirlar.append("</body></html>")
    return "\n".join(satirlar)


async def _transkript_at(bot: commands.Bot, kanal_id: int | None, isim: str, html: str) -> None:
    if not kanal_id:
        return
    kanal = bot.get_channel(kanal_id)
    if not kanal:
        return
    dosya = discord.File(io.StringIO(html), filename=f"transkript-{isim}-{int(time.time())}.html")
    embed = embeds.taban(
        title=f"📜 Transkript: {isim}",
        description=f"`{len(html)//1024}kb` • {discord.utils.format_dt(discord.utils.utcnow(), style='R')}",
    )
    try:
        await kanal.send(embed=embed, file=dosya)
    except discord.HTTPException:
        pass


# --- kurulum yardımcıları ---
async def _kategori_kur(guild: discord.Guild, destek_rol_id: int | None) -> discord.CategoryChannel:
    for c in guild.categories:
        if c.name.strip().startswith("TALEP"):
            return c
    kategori = await guild.create_category("TALEPLER")
    await kategori.set_permissions(guild.default_role, view_channel=False)
    await kategori.set_permissions(guild.me, view_channel=True, manage_channels=True, manage_messages=True)
    return kategori


def get_persistent_views():
    return [KonuSeciciView(None), TalepYonetView(None)]


class TalepKonularModal(discord.ui.Modal, title="Talep Konuları"):
    def __init__(self, mevcut: list[str]) -> None:
        super().__init__()
        self.add_item(discord.ui.TextInput(
            label="Konular (her satıra bir konu, en fazla 25)",
            style=discord.TextStyle.long, required=True, max_length=1000,
            default="\n".join(mevcut[:25]),
        ))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        metin = self.children[0].value.replace(",", "\n")
        konular = [k.strip() for k in metin.splitlines() if k.strip()][:25]
        if not konular:
            await interaction.response.send_message(
                embed=embeds.hata("En az bir konu yazmalısın."), ephemeral=True
            )
            return
        db.guncelle(interaction.guild.id, ticket_konular=constants.json_dump(konular))
        tazelendi = await _panel_yenile(interaction.client, interaction.guild.id)
        await interaction.response.send_message(
            embed=embeds.onay(
                f"**{len(konular)}** konu kaydedildi: `{'` `'.join(konular)}`"
                + ("" if tazelendi else " — paneli yenilemek için `/talep-kur` çalıştır")
            ),
            ephemeral=True,
        )


async def _panel_yenile(bot: commands.Bot, guild_id: int) -> bool:
    """Kayıtlı panel mesajını güncel ayarlarla tazeler. Panel yoksa False."""
    s = db.sunucu(guild_id)
    if not s["ticket_panel_kanal_id"] or not s["ticket_panel_mesaj_id"]:
        return False
    kanal = bot.get_channel(s["ticket_panel_kanal_id"])
    if not kanal:
        return False
    try:
        mesaj = await kanal.fetch_message(s["ticket_panel_mesaj_id"])
    except (discord.NotFound, discord.HTTPException):
        return False
    await mesaj.edit(embed=_panel_embed(guild_id), view=KonuSeciciView(bot, db.konular(guild_id)))
    return True


class TalepPanelModal(discord.ui.Modal, title="Talep Panelini Düzenle"):
    def __init__(self, ayar: dict) -> None:
        super().__init__()
        self.add_item(discord.ui.TextInput(
            label="Başlık", required=True, max_length=256,
            default=ayar["baslik"] or "Destek Talebi",
        ))
        self.add_item(discord.ui.TextInput(
            label="Açıklama", style=discord.TextStyle.long, required=False, max_length=1000,
            default=ayar["aciklama"] or "",
        ))
        self.add_item(discord.ui.TextInput(
            label="Görsel URL (fotoğraf)", required=False, max_length=200,
            placeholder="https://...",
            default=ayar["resim"] or "",
        ))
        self.add_item(discord.ui.TextInput(
            label="Alt bilgi (footer metni)", required=False, max_length=100,
            default=ayar["alt"] or "",
        ))
        self.add_item(discord.ui.TextInput(
            label="Renk (#hex, örn. 00BFFF)", required=False, max_length=7,
            default=ayar["renk"] or "",
        ))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        degerler = {
            "ticket_baslik": self.children[0].value.strip(),
            "ticket_aciklama": self.children[1].value.strip(),
            "ticket_resim": self.children[2].value.strip(),
        }
        renk = self.children[4].value.strip().lstrip("#")
        if renk:
            try:
                if len(renk) != 6:
                    raise ValueError
                int(renk, 16)
                degerler["ticket_renk"] = f"#{renk.upper()}"
            except ValueError:
                await interaction.response.send_message(
                    embed=embeds.hata("Renk 6 haneli hex olmalı, örn. `00BFFF`. Diğer alanlar alınmadı."),
                    ephemeral=True,
                )
                return
        degerler["ticket_alt"] = self.children[3].value.strip()
        db.guncelle(interaction.guild.id, **degerler)
        tazelendi = await _panel_yenile(interaction.client, interaction.guild.id)
        await interaction.response.send_message(
            embed=embeds.onay(
                "Panel güncellendi. ✅"
                + ("" if tazelendi else " (Panel mesajı bulunamadı — `/talep-kur` ile tekrar kurun.)")
            ),
            ephemeral=True,
        )


# --- komutlar ---
class TalepCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _admin(self, interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.manage_guild or interaction.user.id == db.constants_owner()

    async def _admin_kontrol(self, interaction: discord.Interaction) -> bool:
        if not self._admin(interaction):
            await interaction.response.send_message(
                embed=embeds.hata("Bu komut yalnızca sunucu yöneticileri içindir."), ephemeral=True
            )
            return False
        return True

    @app_commands.command(name="talep-kur", description="Kategori + panel + log kanalını tek seferde kurar.")
    @app_commands.describe(yetkili="Talepleri görecek yetkili rolü (opsiyonel)")
    async def talep_kur(self, interaction: discord.Interaction, yetkili: discord.Role | None = None) -> None:
        if not await self._admin_kontrol(interaction):
            return
        guild = interaction.guild
        s = db.sunucu(guild.id)

        await interaction.response.defer(ephemeral=True)

        # 1) kategori
        try:
            kategori = await _kategori_kur(guild, s["destek_rol_id"])
            if yetkili:
                await kategori.set_permissions(yetkili, view_channel=True)
            if s["destek_rol_id"] and s["destek_rol_id"] != (yetkili.id if yetkili else None):
                eski = guild.get_role(s["destek_rol_id"])
                if eski:
                    await kategori.set_permissions(eski, view_channel=True)
        except discord.Forbidden:
            await interaction.followup.send(
                embed=embeds.hata("Botun kategori/kanal yönetme yetkisi yok. Yetkileri kontrol et."), ephemeral=True
            )
            return

        # 2) panel kanalı (sunucu kökünde, herkese görünür)
        panel_kanal = None
        if s["ticket_panel_kanal_id"]:
            panel_kanal = guild.get_channel(s["ticket_panel_kanal_id"])
        if not panel_kanal:
            for c in guild.text_channels:
                if c.name.lower().startswith("talep-panel"):
                    panel_kanal = c
                    break
        if not panel_kanal:
            try:
                panel_kanal = await guild.create_text_channel("talep-panel")
            except discord.Forbidden:
                await interaction.followup.send(embed=embeds.hata("Panel kanalı oluşturulamadı."), ephemeral=True)
                return

        # 3) log kanalı (kategorinin içinde)
        log_kanal = None
        if s["log_kanal_id"]:
            log_kanal = guild.get_channel(s["log_kanal_id"])
        if not log_kanal:
            for c in guild.text_channels:
                if c.name.lower().startswith("talep-log"):
                    log_kanal = c
                    break
        if not log_kanal:
            try:
                log_kanal = await guild.create_text_channel("talep-log", category=kategori)
            except discord.Forbidden:
                log_kanal = None

        # 4) panel mesajı
        view = KonuSeciciView(self.bot, db.konular(guild.id))
        mesaj = None
        if s["ticket_panel_mesaj_id"]:
            try:
                eski_mesaj = await panel_kanal.fetch_message(s["ticket_panel_mesaj_id"])
                mesaj = eski_mesaj
            except (discord.NotFound, discord.HTTPException):
                mesaj = None
        if mesaj:
            await mesaj.edit(embed=_panel_embed(guild.id), view=view)
        else:
            mesaj = await panel_kanal.send(embed=_panel_embed(guild.id), view=view)

        db.guncelle(
            guild.id,
            ticket_kategori_id=kategori.id,
            destek_rol_id=yetkili.id if yetkili else s["destek_rol_id"],
            log_kanal_id=log_kanal.id if log_kanal else s["log_kanal_id"],
            ticket_panel_kanal_id=panel_kanal.id,
            ticket_panel_mesaj_id=mesaj.id,
        )

        embed = embeds.taban(
            title="✅ Talep sistemi kuruldu",
            description=(
                f"**Panel:** {panel_kanal.mention}\n"
                f"**Kategori:** {kategori.mention}\n"
                f"**Log kanalı:** {log_kanal.mention if log_kanal else '❌ kurulamadı'}\n"
                f"**Yetkili rol:** {yetkili.mention if yetkili else '❌ set edilmedi (opsiyonel)'}"
            ),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="talep-panel", description="Panel mesajının fotoğrafını, başlığını ve düzenini düzenle.")
    async def talep_panel(self, interaction: discord.Interaction) -> None:
        if not await self._admin_kontrol(interaction):
            return
        await interaction.response.send_modal(TalepPanelModal(db.ticket_embed_ayar(interaction.guild.id)))

    @app_commands.command(name="talep-kategori", description="Taleplerin açılacağı kategoriyi değiştir.")
    async def talep_kategori(self, interaction: discord.Interaction, kategori: discord.CategoryChannel) -> None:
        if not await self._admin_kontrol(interaction):
            return
        guild = interaction.guild
        try:
            await kategori.set_permissions(guild.default_role, view_channel=False)
            await kategori.set_permissions(guild.me, view_channel=True, manage_channels=True, manage_messages=True)
            s = db.sunucu(guild.id)
            if s["destek_rol_id"]:
                rol = guild.get_role(s["destek_rol_id"])
                if rol:
                    await kategori.set_permissions(rol, view_channel=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=embeds.hata("Botun bu kategoriyi düzenleme yetkisi yok."), ephemeral=True
            )
            return
        db.guncelle(guild.id, ticket_kategori_id=kategori.id)
        await interaction.response.send_message(
            embed=embeds.onay(f"Talepler artık {kategori.mention} kategorisinde açılacak.")
        )

    @app_commands.command(name="talep-yetkili", description="Talepleri görecek yetkili rolünü değiştir.")
    async def talep_yetkili(self, interaction: discord.Interaction, rol: discord.Role) -> None:
        if not await self._admin_kontrol(interaction):
            return
        guild = interaction.guild
        db.guncelle(guild.id, destek_rol_id=rol.id)
        if guild.get_channel(db.sunucu(guild.id)["ticket_kategori_id"] or 0) is not None:
            kategori = guild.get_channel(db.sunucu(guild.id)["ticket_kategori_id"])
            try:
                await kategori.set_permissions(rol, view_channel=True)
            except (discord.Forbidden, discord.HTTPException, AttributeError):
                pass
        await interaction.response.send_message(embed=embeds.onay(f"Yetkili rol: {rol.mention}"))

    @app_commands.command(name="talep-konular", description="Talep konularını düzenle (form açılır; virgülle de geçebilirsin).")
    @app_commands.describe(liste="Opsiyonel: virgülle ayır, örn. a,b,c (boş bırakırsan form açılır)")
    async def talep_konular(self, interaction: discord.Interaction, liste: str | None = None) -> None:
        if not await self._admin_kontrol(interaction):
            return
        if liste is not None:
            konular = [k.strip() for k in liste.split(",") if k.strip()][:25]
            if not konular:
                await interaction.response.send_message(
                    embed=embeds.hata("En az bir konu vermelisin."), ephemeral=True
                )
                return
            db.guncelle(interaction.guild.id, ticket_konular=constants.json_dump(konular))
            tazelendi = await _panel_yenile(interaction.client, interaction.guild.id)
            await interaction.response.send_message(
                embed=embeds.onay(f"Konular güncellendi: `{'` `'.join(konular)}`"
                                  + ("" if tazelendi else " — panel mesajına yansıması için `/talep-kur` çalıştırın"))
            )
            return
        await interaction.response.send_modal(TalepKonularModal(db.konular(interaction.guild.id)))

    @app_commands.command(name="talep-kapat", description="Bir talebi kapat (kanal belirtilmezse bulunduğun kanal).")
    async def talep_kapat(self, interaction: discord.Interaction, kanal: discord.TextChannel | None = None) -> None:
        hedef = kanal or interaction.channel
        kayit = db.ticket_bul(hedef.id)
        if not kayit:
            await interaction.response.send_message(
                embed=embeds.hata("Bu kanal aktif bir talep değil."), ephemeral=True
            )
            return
        if interaction.user.id != kayit["user_id"] and not _staff_mi(interaction):
            await interaction.response.send_message(
                embed=embeds.hata("Bu talebi kapatma yetkin yok."), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        t = None
        try:
            t = await _transkript_al(hedef)
        except Exception:
            t = None
        s = db.sunucu(interaction.guild.id)
        if t and s["log_kanal_id"]:
            await _transkript_at(interaction.client, s["log_kanal_id"], hedef.name, t)
        db.ticket_kapat(hedef.id, t)
        db.log_kaydet(interaction.guild.id, "talep_kapat", f"{hedef.id} kapat:{interaction.user.id}")
        await interaction.followup.send(embed=embeds.onay("Talep kapatılıyor..."), ephemeral=True)
        await asyncio.sleep(3)
        try:
            await hedef.delete(reason="Talep kapatıldı.")
        except discord.HTTPException:
            pass

    @app_commands.command(name="taleplerikapat", description="Sunucudaki TÜM açık talepleri kapatır (transkriptli).")
    async def taleplerikapat(self, interaction: discord.Interaction) -> None:
        if not await self._admin_kontrol(interaction):
            return
        acik = db.tikets_getir(interaction.guild.id, "acik")
        acik = [t for t in acik if t["kanal_id"]]
        if not acik:
            await interaction.response.send_message(embed=embeds.hata("Açık talep yok."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        kapatilan = 0
        for kayit in acik:
            kanal = interaction.guild.get_channel(kayit["kanal_id"])
            if not kanal:
                db.ticket_kapat(kayit["kanal_id"], None)
                kapatilan += 1
                continue
            t, _ = None, None
            try:
                t = await _transkript_al(kanal)
            except Exception:
                t = None
            s = db.sunucu(interaction.guild.id)
            if t and s["log_kanal_id"]:
                await _transkript_at(interaction.client, s["log_kanal_id"], kanal.name, t)
            db.ticket_kapat(kayit["kanal_id"], t)
            db.log_kaydet(interaction.guild.id, "talep_kapat", f"{kayit['kanal_id']} toplu kapanış:{interaction.user.id}")
            try:
                await kanal.delete(reason="Toplu talep kapanışı.")
            except discord.HTTPException:
                pass
            kapatilan += 1
            await asyncio.sleep(1)
        await interaction.followup.send(embed=embeds.onay(f"**{kapatilan}** talep kapatıldı."), ephemeral=True)

    @app_commands.command(name="talep-transkript", description="Bir kanalın transkriptini log kanalına atar.")
    async def talep_transkript(self, interaction: discord.Interaction, kanal: discord.TextChannel | None = None) -> None:
        if not _staff_mi(interaction):
            await interaction.response.send_message(embed=embeds.hata("Yetkin yok."), ephemeral=True)
            return
        hedef = kanal or interaction.channel
        await interaction.response.defer(ephemeral=True)
        t = await _transkript_al(hedef)
        if not t:
            await interaction.followup.send(embed=embeds.hata("Bu kanalda transkript alınacak mesaj yok."), ephemeral=True)
            return
        s = db.sunucu(interaction.guild.id)
        if s["log_kanal_id"]:
            await _transkript_at(interaction.client, s["log_kanal_id"], hedef.name, t)
        await interaction.followup.send(embed=embeds.onay("Transkript log kanalına atıldı."), ephemeral=True)

    @app_commands.command(name="talep-gor", description="Talep sistemi yapılandırmasını gösterir.")
    async def talep_gor(self, interaction: discord.Interaction) -> None:
        if not _staff_mi(interaction):
            await interaction.response.send_message(embed=embeds.hata("Yetkin yok."), ephemeral=True)
            return
        s = db.sunucu(interaction.guild.id)
        acik = len(db.tikets_getir(interaction.guild.id, "acik"))
        kapatilan = len(db.tikets_getir(interaction.guild.id, "kapali"))
        embed = embeds.taban(title="🎫 Talep Sistemi")
        embed.add_field(name="Panel", value=f"<#{s['ticket_panel_kanal_id']}>" if s["ticket_panel_kanal_id"] else "❌", inline=True)
        embed.add_field(name="Kategori", value=f"<#{s['ticket_kategori_id']}>" if s["ticket_kategori_id"] else "❌", inline=True)
        embed.add_field(name="Log", value=f"<#{s['log_kanal_id']}>" if s["log_kanal_id"] else "❌", inline=True)
        embed.add_field(name="Yetkili rol", value=f"<@&{s['destek_rol_id']}>" if s["destek_rol_id"] else "❌", inline=True)
        embed.add_field(name="Konular", value=", ".join(db.konular(interaction.guild.id)), inline=False)
        embed.add_field(name="Durum", value=f"**{acik}** açık / **{kapatilan}** kapatıldı", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TalepCog(bot))