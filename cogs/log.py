"""Loglama sistemi: log kanalı ayarı, olay dinleyicileri, log geçmişi komutu."""
import discord
from discord import app_commands
from discord.ext import commands

from utils import db, embeds


class LogCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def log_kanal(self, guild: discord.Guild):
        s = db.sunucu(guild.id)
        return self.bot.get_channel(s["log_kanal_id"]) if s["log_kanal_id"] else None

    async def _log(self, guild: discord.Guild, tur: str, icerik: str, renk: int = 0x00BFFF) -> None:
        kanal = self.log_kanal(guild)
        if kanal:
            try:
                embed = embeds.taban(title=f"{tur}", description=icerik, color=renk)
                embed.timestamp = discord.utils.utcnow()
                await kanal.send(embed=embed)
            except discord.HTTPException:
                pass
        db.log_kaydet(guild.id, tur.lower().replace(" ", "_"), icerik)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self._log(
            member.guild, "👋 Üye katıldı",
            f"{member.mention} (`{member.id}`) sunucuya katıldı.\n"
            f"**Kayıt:** {discord.utils.format_dt(member.created_at, style='R')}",
            0x2ECC71,
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await self._log(
            member.guild, "🚪 Üye ayrıldı",
            f"{member.mention} (`{member.id}`) sunucudan ayrıldı veya atıldı.",
            0xE74C3C,
        )

    @commands.Cog.listener()
    async def on_message_edit(self, onceki: discord.Message, sonraki: discord.Message) -> None:
        if onceki.author.bot or onceki.content == sonraki.content or onceki.guild is None:
            return
        if onceki.content == "" or sonraki.content == "":
            return
        await self._log(
            onceki.guild, "✏️ Mesaj düzenlendi",
            f"**Kanal:** {onceki.channel.mention}\n**Yazar:** {onceki.author.mention}\n"
            f"**Önce:** {onceki.content[:900]}\n**Sonra:** {sonraki.content[:900]}",
            0xF1C40F,
        )

    @commands.Cog.listener()
    async def on_message_delete(self, mesaj: discord.Message) -> None:
        if mesaj.author.bot or mesaj.guild is None:
            return
        icerik = mesaj.content[:900] or "(metin yok)"
        ekler = ""
        if mesaj.attachments:
            ekler = "\n" + "\n".join(e.url for e in mesaj.attachments[:3])
        await self._log(
            mesaj.guild, "🗑️ Mesaj silindi",
            f"**Kanal:** {mesaj.channel.mention}\n**Yazar:** {mesaj.author.mention} (`{mesaj.author.id}`)\n"
            f"**İçerik:** {icerik}{ekler}",
            0xE74C3C,
        )

    @commands.Cog.listener()
    async def on_member_update(self, onceki: discord.Member, sonraki: discord.Member) -> None:
        if onceki.nick != sonraki.nick:
            await self._log(
                sonraki.guild, "🏷️ İsim değişti",
                f"**Üye:** {sonraki.mention}\n**Eski:** {onceki.nick or onceki.display_name}\n"
                f"**Yeni:** {sonraki.nick or sonraki.display_name}",
                0x00BFFF,
            )
        if onceki.roles != sonraki.roles:
            rol_eklendi = [r.mention for r in set(sonraki.roles) - set(onceki.roles)]
            rol_silindi = [r.mention for r in set(onceki.roles) - set(sonraki.roles)]
            detaylar = []
            if rol_eklendi:
                detaylar.append(f"➕ Rol eklendi: {', '.join(rol_eklendi)}")
            if rol_silindi:
                detaylar.append(f"➖ Rol alındı: {', '.join(rol_silindi)}")
            if detaylar:
                await self._log(
                    sonraki.guild, "🎭 Rol değişikliği",
                    f"**Üye:** {sonraki.mention}\n" + "\n".join(detaylar),
                    0x9B59B6,
                )

    @commands.Cog.listener()
    async def on_guild_channel_create(self, kanal: discord.abc.GuildChannel) -> None:
        await self._log(kanal.guild, "📁 Kanal oluşturuldu", f"{kanal.mention} oluşturuldu.", 0x2ECC71)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, kanal: discord.abc.GuildChannel) -> None:
        await self._log(kanal.guild, "📁 Kanal silindi", f"`{kanal.name}` silindi.", 0xE74C3C)

    @commands.Cog.listener()
    async def on_guild_role_create(self, rol: discord.Role) -> None:
        await self._log(rol.guild, "⭐ Rol oluşturuldu", f"`{rol.name}` oluşturuldu.", 0x2ECC71)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, rol: discord.Role) -> None:
        await self._log(rol.guild, "⭐ Rol silindi", f"`{rol.name}` silindi.", 0xE74C3C)

    # --- komutlar ---
    @app_commands.command(name="log-kanal", description="Tüm logların gideceği kanalı ayarla.")
    async def log_kanal_komut(self, interaction: discord.Interaction, kanal: discord.TextChannel) -> None:
        if not (interaction.user.guild_permissions.manage_guild or interaction.user.id == db.constants_owner()):
            await interaction.response.send_message(
                embed=embeds.hata("Bu komut yalnızca sunucu yöneticileri içindir."), ephemeral=True
            )
            return
        db.guncelle(interaction.guild.id, log_kanal_id=kanal.id)
        await interaction.response.send_message(embed=embeds.onay(f"Log kanalı: {kanal.mention}"))

    @app_commands.command(name="log-gecmis", description="Son log kayıtlarını listele.")
    async def log_gecmis(self, interaction: discord.Interaction, adet: int = 10) -> None:
        if not (interaction.user.guild_permissions.manage_guild or interaction.user.id == db.constants_owner()):
            await interaction.response.send_message(
                embed=embeds.hata("Bu komut yalnızca sunucu yöneticileri içindir."), ephemeral=True
            )
            return
        adet = max(1, min(adet, 50))
        kayitlar = db.log_gecmis_getir(interaction.guild.id, adet)

        if not kayitlar:
            await interaction.response.send_message(embed=embeds.hata("Henüz log kaydı yok."), ephemeral=True)
            return

        sayfalar = []
        for i in range(0, len(kayitlar), 8):
            blok = kayitlar[i:i + 8]
            embed = embeds.taban(
                title="📜 Log Geçmişi",
                description=f"Toplam {len(kayitlar)} kayıt gösteriliyor.",
            )
            for kayit in blok:
                zaman = discord.utils.format_dt(discord.utils.utcnow().fromtimestamp(kayit["zaman"]), style="R")
                embed.add_field(
                    name=f"`{kayit['id']}` • {kayit['tur']}",
                    value=f"{kayit['detay'][:120]}\n*{zaman}*",
                    inline=False,
                )
            sayfalar.append(embed)

        if len(sayfalar) == 1:
            await interaction.response.send_message(embed=sayfalar[0], ephemeral=True)
        else:
            from utils import paginator
            await interaction.response.send_message(
                embed=sayfalar[0], view=paginator.Sayfalayici(sayfalar, interaction.user.id), ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LogCog(bot))