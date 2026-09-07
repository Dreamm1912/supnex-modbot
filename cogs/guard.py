"""Guard sistemi: anti-raid, ban/kanal/rol koruması, beyaz liste, loglama."""
import asyncio
import time

import discord
from discord import app_commands
from discord.ext import commands

from utils import db, embeds

RAID_ESIGI = 5
RAID_PENCERE = 10


class GuardCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.katilma_gecmisi: dict[int, list[float]] = {}

    # --- yardımcılar ---
    def yetkili_mi(self, interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.administrator or interaction.user.id == db.constants_owner()

    async def _yetki_kontrol(self, interaction: discord.Interaction) -> bool:
        if not self.yetkili_mi(interaction):
            await interaction.response.send_message(
                embed=embeds.hata("Bu komut yalnızca sunucu yöneticileri içindir."), ephemeral=True
            )
            return False
        return True

    def _aktoru_guvenli(self, guild: discord.Guild, user_id: int) -> bool:
        """Guard'ın engellememesi gereken aktörler: bot, sahip, yönetici, mod rolü, beyaz liste."""
        if user_id in (guild.me.id, guild.owner_id) or user_id == db.constants_owner():
            return True
        uye = guild.get_member(user_id)
        if uye and (uye.guild_permissions.administrator or uye.guild_permissions.ban_members
                    or uye.guild_permissions.manage_guild):
            return True
        s = db.sunucu(guild.id)
        if s["mod_rol_id"]:
            rol = guild.get_role(s["mod_rol_id"])
            if rol and uye and rol in uye.roles:
                return True
        return db.guvenli_mi(guild.id, user_id)

    async def logla(self, guild: discord.Guild, tur: str, detay: str, renk: int = 0x00BFFF) -> None:
        s = db.sunucu(guild.id)
        if not s["log_kanal_id"]:
            return
        kanal = self.bot.get_channel(s["log_kanal_id"])
        if kanal:
            try:
                await kanal.send(embed=embeds.taban(title=f"🛡️ Guard • {tur}", description=detay, color=renk))
            except discord.HTTPException:
                pass
        db.log_kaydet(guild.id, f"guard_{tur.lower()}", detay)

    # --- ant-raid: hızlı katılımları yakala ---
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        g = db.guard(member.guild.id)
        if not g["aktif"] or not g["anti_raid"]:
            return
        now = time.time()
        self.katilma_gecmisi.setdefault(member.guild.id, []).append(now)
        pencere = [t for t in self.katilma_gecmisi[member.guild.id] if now - t <= RAID_PENCERE]
        self.katilma_gecmisi[member.guild.id] = pencere
        if len(pencere) >= RAID_ESIGI:
            try:
                await member.ban(reason="Anti-raid: hızlı katılım akını")
                await self.logla(
                    member.guild, "raid", f"**Anti-raid tetiklendi.** {RAID_ESIGI}+ katılım / {RAID_PENCERE}sn. "
                                           f"{member.mention} (`{member.id}`) banlandı.", 0xE74C3C
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        g = db.guard(guild.id)
        if not g["aktif"] or not g["ban_korumasi"]:
            return
        try:
            denetim = [e async for e in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban)]
        except discord.HTTPException:
            return
        if not denetim:
            return
        e = denetim[0]
        if self._aktoru_guvenli(guild, e.user.id):
            return
        try:
            await guild.unban(user, reason="Anti-nuke: yetkisiz ban koruması")
            await self.logla(
                guild, "ban_korumasi",
                f"**Yetkisiz ban tespit edildi.** Banlayan: {e.user.mention} — ban kaldırıldı: {user.mention}.",
                0xE74C3C,
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.Cog.listener()
    async def on_guild_channel_create(self, kanal: discord.abc.GuildChannel) -> None:
        guild = kanal.guild
        g = db.guard(guild.id)
        if not g["aktif"] or not g["kanal_korumasi"]:
            return
        try:
            denetim = [e async for e in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create)]
        except discord.HTTPException:
            return
        if not denetim:
            return
        e = denetim[0]
        if self._aktoru_guvenli(guild, e.user.id):
            return
        try:
            await kanal.delete(reason="Anti-nuke: yetkisiz kanal oluşturma")
            await self.logla(
                guild, "kanal_korumasi",
                f"**Yetkisiz kanal oluşturma engellendi.** Oluşturan: {e.user.mention} — `#{kanal.name}` silindi.",
                0xE74C3C,
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.Cog.listener()
    async def on_guild_role_create(self, rol: discord.Role) -> None:
        guild = rol.guild
        g = db.guard(guild.id)
        if not g["aktif"] or not g["rol_korumasi"]:
            return
        try:
            denetim = [e async for e in guild.audit_logs(limit=1, action=discord.AuditLogAction.role_create)]
        except discord.HTTPException:
            return
        if not denetim:
            return
        e = denetim[0]
        if self._aktoru_guvenli(guild, e.user.id):
            return
        try:
            await rol.delete(reason="Anti-nuke: yetkisiz rol oluşturma")
            await self.logla(
                guild, "rol_korumasi",
                f"**Yetkisiz rol oluşturma engellendi.** Oluşturan: {e.user.mention} — `{rol.name}` silindi.",
                0xE74C3C,
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        db.guard(guild.id)

    # --- komutlar ---
    guard_grubu = app_commands.Group(name="guard", description="Anti-raid / anti-nuke koruma sistemi")

    @guard_grubu.command(name="durum", description="Guard durumunu gör.")
    async def durum(self, interaction: discord.Interaction) -> None:
        g = db.guard(interaction.guild.id)
        liste = db.json_load(g["beyaz_liste"], [])
        embed = embeds.taban(title="🛡️ Guard Durumu")
        embed.add_field(name="Sistem", value="🟢 Aktif" if g["aktif"] else "🔴 Pasif", inline=True)
        embed.add_field(name="Ban koruması", value="Açık" if g["ban_korumasi"] else "Kapalı", inline=True)
        embed.add_field(name="Kanal koruması", value="Açık" if g["kanal_korumasi"] else "Kapalı", inline=True)
        embed.add_field(name="Rol koruması", value="Açık" if g["rol_korumasi"] else "Kapalı", inline=True)
        embed.add_field(name="Anti-raid", value="Açık" if g["anti_raid"] else "Kapalı", inline=True)
        embed.add_field(name="Beyaz liste", value=f"{len(liste)} kişi", inline=True)
        embed.add_field(
            name="Beyaz listedekiler",
            value=", ".join(f"<@{i}>" for i in liste[:10]) or "Boş",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @guard_grubu.command(name="ac", description="Guard sistemini aç.")
    async def ac(self, interaction: discord.Interaction) -> None:
        if not await self._yetki_kontrol(interaction):
            return
        db.guard_guncelle(interaction.guild.id, aktif=1)
        await interaction.response.send_message(embed=embeds.onay("Guard **AÇILDI**. Sunucu koruma altında."))

    @guard_grubu.command(name="kapat", description="Guard sistemini kapat.")
    async def kapat(self, interaction: discord.Interaction) -> None:
        if not await self._yetki_kontrol(interaction):
            return
        db.guard_guncelle(interaction.guild.id, aktif=0)
        await interaction.response.send_message(embed=embeds.uyari_yaz("Guard **KAPATILDI**. Korumalar devre dışı."))

    @guard_grubu.command(name="koruma", description="Tek korumayı aç/kapat (ban, kanal, rol, raid).")
    @app_commands.describe(tur="Hangi koruma?", durum="acik / kapali")
    async def koruma(self, interaction: discord.Interaction, tur: str, durum: str) -> None:
        if not await self._yetki_kontrol(interaction):
            return
        tur = tur.lower()
        if tur not in ("ban", "kanal", "rol", "raid"):
            await interaction.response.send_message(
                embed=embeds.hata("Tur: `ban`, `kanal`, `rol` veya `raid` olmalı."), ephemeral=True
            )
            return
        durum = durum.lower()
        if durum not in ("acik", "kapali", "açık", "açık"):
            await interaction.response.send_message(embed=embeds.hata("Durum: `acik` veya `kapali`."), ephemeral=True)
            return
        deger = 1 if durum.startswith("a") else 0
        alan = {"ban": "ban_korumasi", "kanal": "kanal_korumasi", "rol": "rol_korumasi", "raid": "anti_raid"}[tur]
        db.guard_guncelle(interaction.guild.id, **{alan: deger})
        isim = {"ban": "Ban", "kanal": "Kanal", "rol": "Rol", "raid": "Anti-raid"}[tur]
        await interaction.response.send_message(
            embed=embeds.onay(f"{isim} koruması: **{'AÇIK' if deger else 'KAPALI'}**")
        )

    @guard_grubu.command(name="yetkili", description="Guard'ı bypass edecek güvenli kişi ekle/çıkar.")
    @app_commands.describe(uye="Beyaz listeye alınacak üye.", islem="ekle / cikar")
    async def yetkili(self, interaction: discord.Interaction, uye: discord.Member, islem: str = "ekle") -> None:
        if not await self._yetki_kontrol(interaction):
            return
        g = db.guard(interaction.guild.id)
        liste = db.json_load(g["beyaz_liste"], [])
        if islem.lower() == "cikar" or islem.lower().startswith("ç"):
            if uye.id in liste:
                liste.remove(uye.id)
                db.guard_guncelle(interaction.guild.id, beyaz_liste=db.json_dump(liste))
                await interaction.response.send_message(embed=embeds.onay(f"{uye.mention} beyaz listeden çıkarıldı."))
            else:
                await interaction.response.send_message(embed=embeds.hata("Bu kişi zaten listede değil."), ephemeral=True)
            return
        if uye.id in liste:
            await interaction.response.send_message(embed=embeds.hata("Bu kişi zaten beyaz listede."), ephemeral=True)
            return
        liste.append(uye.id)
        db.guard_guncelle(interaction.guild.id, beyaz_liste=db.json_dump(liste))
        await interaction.response.send_message(embed=embeds.onay(f"{uye.mention} beyaz listeye eklendi. Guard'ı bypass eder."))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GuardCog(bot))