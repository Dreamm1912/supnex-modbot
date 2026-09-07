"""Moderasyon komutları: at, ban, sustur, uyar, temizle, kilit, yavaş mod, rol işlemleri."""
import datetime

import discord
from discord import app_commands
from discord.ext import commands

from utils import db, embeds


def _mod_mi(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.ban_members or interaction.user.guild_permissions.manage_messages:
        return True
    if interaction.user.id == db.constants_owner():
        return True
    s = db.sunucu(interaction.guild.id)
    if s["mod_rol_id"]:
        rol = interaction.guild.get_role(s["mod_rol_id"])
        if rol and rol in interaction.user.roles:
            return True
    return False


def _mod_kontrol(interaction: discord.Interaction) -> bool:
    if not _mod_mi(interaction):
        return False
    return True


async def _log_yetkili(interaction: discord.Interaction, baslik: str, detay: str, renk: int = 0x00BFFF) -> None:
    db.log_kaydet(interaction.guild.id, baslik.lower(), detay)
    s = db.sunucu(interaction.guild.id)
    if not s["log_kanal_id"]:
        return
    kanal = interaction.client.get_channel(s["log_kanal_id"])
    if kanal:
        try:
            await kanal.send(embed=embeds.taban(title=baslik, description=detay, color=renk))
        except discord.HTTPException:
            pass


class ModerasyonCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="mod-rol", description="Moderatör rolünü belirle (moderasyon komutlarını kullanabilir).")
    async def mod_rol(self, interaction: discord.Interaction, rol: discord.Role) -> None:
        if not (interaction.user.guild_permissions.manage_guild or interaction.user.id == db.constants_owner()):
            await interaction.response.send_message(embed=embeds.hata("Yeterli yetkin yok."), ephemeral=True)
            return
        db.guncelle(interaction.guild.id, mod_rol_id=rol.id)
        await interaction.response.send_message(
            embed=embeds.onay(f"Moderatör rolü: {rol.mention}. Bu rol moderasyon komutlarını kullanabilir.")
        )

    async def _yetki(self, interaction: discord.Interaction) -> bool:
        if not _mod_kontrol(interaction):
            await interaction.response.send_message(
                embed=embeds.hata("Bu komutu kullanmak için moderatör olmalısın."), ephemeral=True
            )
            return False
        return True

    @app_commands.command(name="at", description="Üyeyi sunucudan at.")
    async def at(self, interaction: discord.Interaction, uye: discord.Member, sebep: str = "Sebep belirtilmedi") -> None:
        if not await self._yetki(interaction):
            return
        if not interaction.guild.me.guild_permissions.ban_members or not interaction.guild.me.guild_permissions.kick_members:
            await interaction.response.send_message(embed=embeds.hata("Botun üye atma yetkisi yok."), ephemeral=True)
            return
        if uye.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message(embed=embeds.hata("Bu üyeyi atamam, rolüm yetmiyor."), ephemeral=True)
            return
        try:
            await uye.kick(reason=sebep)
        except (discord.Forbidden, discord.HTTPException) as hata:
            await interaction.response.send_message(embed=embeds.hata(f"Atılamadı: {hata}"), ephemeral=True)
            return
        await interaction.response.send_message(
            embed=embeds.taban(title="👢 Üye atıldı",
                               description=f"**{uye.mention}** sunucudan atıldı.\n**Sebep:** {sebep}\n**Moderatör:** {interaction.user.mention}",
                               color=0xF1C40F)
        )
        await _log_yetkili(interaction, "at", f"{uye.id} atıldı. Sebep: {sebep}. Atan: {interaction.user.id}", 0xF1C40F)

    @app_commands.command(name="ban", description="Üyeyi sunucudan yasakla.")
    async def ban(self, interaction: discord.Interaction, uye: discord.User, sebep: str = "Sebep belirtilmedi") -> None:
        if not await self._yetki(interaction):
            return
        if not interaction.guild.me.guild_permissions.ban_members:
            await interaction.response.send_message(embed=embeds.hata("Botun üye yasaklama yetkisi yok."), ephemeral=True)
            return
        if isinstance(uye, discord.Member) and uye.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message(embed=embeds.hata("Bu üyeyi banlayamam, rolüm yetmiyor."), ephemeral=True)
            return
        try:
            await interaction.guild.ban(uye, reason=sebep)
        except (discord.Forbidden, discord.HTTPException) as hata:
            await interaction.response.send_message(embed=embeds.hata(f"Banlanamadı: {hata}"), ephemeral=True)
            return
        await interaction.response.send_message(
            embed=embeds.taban(title="🔨 Üye banlandı",
                               description=f"**{uye.mention}** sunucudan yasaklandı.\n**Sebep:** {sebep}\n**Moderatör:** {interaction.user.mention}")
        )
        await _log_yetkili(interaction, "ban", f"{uye.id} banlandı. Sebep: {sebep}. Banlayan: {interaction.user.id}")

    @app_commands.command(name="ban-kaldir", description="Yasaklı üyenin banını kaldır.")
    async def ban_kaldir(self, interaction: discord.Interaction, uye: discord.User) -> None:
        if not await self._yetki(interaction):
            return
        try:
            await interaction.guild.unban(uye)
        except discord.HTTPException:
            await interaction.response.send_message(embed=embeds.hata("Bu üye yasaklı değil."), ephemeral=True)
            return
        await interaction.response.send_message(embed=embeds.onay(f"{uye.mention} banı kaldırıldı."))
        await _log_yetkili(interaction, "ban-kaldir", f"{uye.id} banı kaldırıldı. Yapan: {interaction.user.id}")

    @app_commands.command(name="sustur", description="Üyeyi belirli süre sustur (örn. 10dk, 1sa).")
    async def sustur(self, interaction: discord.Interaction, uye: discord.Member, sure: str = "10dk",
                     sebep: str = "Sebep belirtilmedi") -> None:
        if not await self._yetki(interaction):
            return
        if not interaction.guild.me.guild_permissions.moderate_members:
            await interaction.response.send_message(embed=embeds.hata("Botun susturma yetkisi yok."), ephemeral=True)
            return
        saniye = None
        giris = sure.lower().strip()
        try:
            if giris.endswith("dk"):
                saniye = int(giris[:-2]) * 60
            elif giris.endswith("sa"):
                saniye = int(giris[:-2]) * 3600
            elif giris.endswith("sn"):
                saniye = int(giris[:-2])
            else:
                saniye = int(giris)
        except (ValueError, TypeError):
            await interaction.response.send_message(embed=embeds.hata("Süre formatı: örn. `10dk`, `2sa`, `30sn`."), ephemeral=True)
            return
        saniye = max(60, min(saniye, 28 * 86400))
        if uye.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message(embed=embeds.hata("Bu üyeyi susturamam."), ephemeral=True)
            return
        try:
            await uye.timeout(discord.utils.utcnow() + datetime.timedelta(seconds=saniye), reason=sebep)
        except (discord.Forbidden, discord.HTTPException) as hata:
            await interaction.response.send_message(embed=embeds.hata(f"Susturulamadı: {hata}"), ephemeral=True)
            return
        await interaction.response.send_message(
            embed=embeds.taban(title="🤐 Üye susturuldu",
                               description=f"**{uye.mention}** için timeout: `{sure}`\n**Sebep:** {sebep}",
                               color=0x9B59B6)
        )
        await _log_yetkili(interaction, "sustur", f"{uye.id} {saniye}sn susturuldu. Sebep: {sebep}. Yapan: {interaction.user.id}")

    @app_commands.command(name="sustur-kaldir", description="Üyenin susturulmasını kaldır.")
    async def sustur_kaldir(self, interaction: discord.Interaction, uye: discord.Member) -> None:
        if not await self._yetki(interaction):
            return
        if not interaction.guild.me.guild_permissions.moderate_members:
            await interaction.response.send_message(embed=embeds.hata("Botun yetkisi yok."), ephemeral=True)
            return
        try:
            await uye.timeout(None)
        except (discord.Forbidden, discord.HTTPException) as hata:
            await interaction.response.send_message(embed=embeds.hata(f"Kaldırılamadı: {hata}"), ephemeral=True)
            return
        await interaction.response.send_message(embed=embeds.onay(f"{uye.mention} susturması kaldırıldı."))
        await _log_yetkili(interaction, "sustur-kaldir", f"{uye.id} susturması kaldırıldı. Yapan: {interaction.user.id}")

    @app_commands.command(name="uyar", description="Üyeye uyarı ekle.")
    async def uyar(self, interaction: discord.Interaction, uye: discord.Member, sebep: str = "Sebep belirtilmedi") -> None:
        if not await self._yetki(interaction):
            return
        db.uyar_ekle(interaction.guild.id, uye.id, interaction.user.id, sebep)
        sayi = len(db.uyarilari_getir(interaction.guild.id, uye.id))
        embed = embeds.taban(title="⚠️ Uyarı eklendi",
                             description=f"**{uye.mention}** bir uyarı aldı. **Toplam uyarı:** {sayi}\n**Sebep:** {sebep}",
                             color=0xF1C40F)
        try:
            await uye.send(embed=embeds.uyari_yaz(f"{interaction.guild.name} sunucusunda uyarı aldın.\n**Sebep:** {sebep}"))
        except discord.HTTPException:
            pass
        await interaction.response.send_message(embed=embed)
        await _log_yetkili(interaction, "uyar", f"{uye.id} uyarıldı. Yapan: {interaction.user.id}. Sebep: {sebep}")

    @app_commands.command(name="uyarilar", description="Üyenin uyarılarını listele.")
    async def uyarilar(self, interaction: discord.Interaction, uye: discord.Member) -> None:
        if not await self._yetki(interaction):
            return
        kayitlar = db.uyarilari_getir(interaction.guild.id, uye.id)
        if not kayitlar:
            await interaction.response.send_message(embed=embeds.hata(f"{uye.mention} hiç uyarı almamış."), ephemeral=True)
            return
        embed = embeds.taban(title=f"⚠️ {uye.display_name} — {len(kayitlar)} uyarı")
        for k in kayitlar[:10]:
            zaman = discord.utils.format_dt(discord.utils.utcnow().fromtimestamp(k["tarih"]), style="R")
            embed.add_field(
                name=f"#{k['id']} • {zaman}",
                value=f"**Sebep:** {k['sebep']}\n**Veren:** <@{k['moderator_id']}>",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="uyartemizle", description="Üyenin tüm uyarılarını temizle.")
    async def uyartemizle(self, interaction: discord.Interaction, uye: discord.Member) -> None:
        if not await self._yetki(interaction):
            return
        silinen = db.uyarlari_temizle(interaction.guild.id, uye.id)
        await interaction.response.send_message(
            embed=embeds.onay(f"{uye.mention} için {silinen} uyarı temizlendi.")
        )
        await _log_yetkili(interaction, "uyartemizle", f"{uye.id} uyarıları temizlendi ({silinen} kayıt). Yapan: {interaction.user.id}")

    @app_commands.command(name="temizle", description="Belirtilen sayıda mesajı sil.")
    async def temizle(self, interaction: discord.Interaction, adet: int) -> None:
        if not await self._yetki(interaction):
            return
        adet = max(1, min(adet, 100))
        if not interaction.guild.me.guild_permissions.manage_messages:
            await interaction.response.send_message(embed=embeds.hata("Botun mesaj silme yetkisi yok."), ephemeral=True)
            return
        try:
            await interaction.response.defer(ephemeral=True)
            silinen = await interaction.channel.purge(limit=adet, bulk=True)
        except discord.HTTPException as hata:
            try:
                await interaction.response.send_message(embed=embeds.hata(f"Silinemedi: {hata}"), ephemeral=True)
            except discord.HTTPException:
                await interaction.followup.send(embed=embeds.hata(f"Silinemedi: {hata}"), ephemeral=True)
            return
        await interaction.followup.send(embed=embeds.onay(f"`{len(silinen)}` mesaj silindi."), ephemeral=True)
        await _log_yetkili(interaction, "temizle", f"{interaction.channel.id} kanalından {len(silinen)} mesaj silindi. Yapan: {interaction.user.id}")

    @app_commands.command(name="kilit", description="Kanalı kilitler (herkes mesaj yazamaz).")
    async def kilit(self, interaction: discord.Interaction) -> None:
        if not await self._yetki(interaction):
            return
        if not interaction.guild.me.guild_permissions.manage_channels:
            await interaction.response.send_message(embed=embeds.hata("Botun kanal yönetme yetkisi yok."), ephemeral=True)
            return
        await interaction.channel.set_permissions(
            interaction.guild.default_role, send_messages=False,
            reason=f"Kilitlendi: {interaction.user}",
        )
        await interaction.response.send_message(embed=embeds.uyari_yaz(f"🔒 {interaction.channel.mention} kilitlendi."))
        await _log_yetkili(interaction, "kilit", f"{interaction.channel.id} kilitlendi. Yapan: {interaction.user.id}")

    @app_commands.command(name="kilit-ac", description="Kanalın kilidini açar.")
    async def kilit_ac(self, interaction: discord.Interaction) -> None:
        if not await self._yetki(interaction):
            return
        if not interaction.guild.me.guild_permissions.manage_channels:
            await interaction.response.send_message(embed=embeds.hata("Botun kanal yönetme yetkisi yok."), ephemeral=True)
            return
        await interaction.channel.set_permissions(
            interaction.guild.default_role, send_messages=None,
            reason=f"Kilit açıldı: {interaction.user}",
        )
        await interaction.response.send_message(embed=embeds.onay(f"🔓 {interaction.channel.mention} kilidi açıldı."))
        await _log_yetkili(interaction, "kilit-ac", f"{interaction.channel.id} kilidi açıldı. Yapan: {interaction.user.id}")

    @app_commands.command(name="yavasmod", description="Kanal için yavaş mod süresi ayarla (saniye, 0 = kapat).")
    async def yavasmod(self, interaction: discord.Interaction, sure: int) -> None:
        if not await self._yetki(interaction):
            return
        if not interaction.guild.me.guild_permissions.manage_channels:
            await interaction.response.send_message(embed=embeds.hata("Botun kanal yönetme yetkisi yok."), ephemeral=True)
            return
        sure = max(0, min(sure, 21600))
        await interaction.channel.edit(slowmode_delay=sure)
        await interaction.response.send_message(
            embed=embeds.onay(f"Yavaş mod: **{sure}sn**." if sure else "Yavaş mod kapatıldı.")
        )

    @app_commands.command(name="rol-ver", description="Üyeye rol ver.")
    async def rol_ver(self, interaction: discord.Interaction, uye: discord.Member, rol: discord.Role) -> None:
        if not await self._yetki(interaction):
            return
        if rol >= interaction.guild.me.top_role:
            await interaction.response.send_message(embed=embeds.hata("Bu rolü veremem, rolüm yetmiyor."), ephemeral=True)
            return
        try:
            await uye.add_roles(rol, reason=f"{interaction.user} tarafından verildi")
        except discord.HTTPException as hata:
            await interaction.response.send_message(embed=embeds.hata(f"Rol verilemedi: {hata}"), ephemeral=True)
            return
        await interaction.response.send_message(embed=embeds.onay(f"{uye.mention} → {rol.mention} rolü verildi."))
        await _log_yetkili(interaction, "rol-ver", f"{uye.id} → {rol.id} rolü verildi. Yapan: {interaction.user.id}")

    @app_commands.command(name="rol-al", description="Üyeden rol al.")
    async def rol_al(self, interaction: discord.Interaction, uye: discord.Member, rol: discord.Role) -> None:
        if not await self._yetki(interaction):
            return
        if rol >= interaction.guild.me.top_role:
            await interaction.response.send_message(embed=embeds.hata("Bu rolü alamam, rolüm yetmiyor."), ephemeral=True)
            return
        try:
            await uye.remove_roles(rol, reason=f"{interaction.user} tarafından alındı")
        except discord.HTTPException as hata:
            await interaction.response.send_message(embed=embeds.hata(f"Rol alınamadı: {hata}"), ephemeral=True)
            return
        await interaction.response.send_message(embed=embeds.onay(f"{uye.mention} → {rol.mention} rolü alındı."))
        await _log_yetkili(interaction, "rol-al", f"{uye.id} → {rol.id} rolü alındı. Yapan: {interaction.user.id}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerasyonCog(bot))