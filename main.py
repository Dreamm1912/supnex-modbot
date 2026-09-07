"""Supnex Mod Bot — ana giriş."""
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from utils import constants, db

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN", "")


class SupnexBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)
        self.synced = False

    async def setup_hook(self) -> None:
        for cog in ("ticket", "guard", "log", "moderation"):
            try:
                await self.load_extension(f"cogs.{cog}")
                print(f"supnex :: cog yüklendi: {cog}")
            except Exception as hata:
                print(f"supnex :: cog hatası ({cog}): {hata}")
                raise
        from cogs.ticket import get_persistent_views
        for gorunum in get_persistent_views():
            self.add_view(gorunum)
            print(f"supnex :: kalici gorunum: {gorunum.__class__.__name__}")

    async def on_ready(self) -> None:
        print(f"supnex :: Giriş: {self.user} (id: {self.user.id})")
        print(f"supnex :: Sunucular: {len(self.guilds)}")
        for guild in self.guilds:
            db.sunucu(guild.id)
            db.guard(guild.id)
        try:
            await self.wait_until_ready()
            synced = await self.tree.sync()
            print(f"supnex :: Slash commands synced ({len(synced)})")
        except Exception as hata:
            print(f"supnex :: sync hatası: {hata}")
        await self._ses_baglan()
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=".gg/supnex"))

    async def _ses_baglan(self) -> None:
        """Kayıtlı ses kanalı varsa bağlan ve streaming rozetini aç."""
        for guild in self.guilds:
            s = db.sunucu(guild.id)
            if not s["ses_kanal_id"]:
                continue
            kanal = guild.get_channel(s["ses_kanal_id"])
            if not kanal:
                continue
            for ses in guild.voice_channels:
                if self.user.id in [m.id for m in ses.members]:
                    await ses.guild.voice_client.disconnect()
                    break
            try:
                await kanal.connect(self_deaf=True)
                await self.change_presence(
                    activity=discord.Streaming(
                        name=".gg/supnex",
                        url="https://www.twitch.tv/supnex",
                    )
                )
                print(f"supnex :: sese bağlandı: {guild.name}/{kanal.name} (streaming açık)")
            except Exception as hata:
                print(f"supnex :: ses bağlantı hatası ({guild.name}): {hata}")


bot = SupnexBot()


@bot.tree.error
async def on_uygulama_hatasi(interaction: discord.Interaction, error: Exception) -> None:
    print(f"supnex :: slash hatası {interaction.command}: {error}")
    if isinstance(error, discord.app_commands.CommandOnCooldown):
        return
    if isinstance(error, discord.app_commands.MissingPermissions):
        embed = discord.Embed(description="❌ Yeterli yetkin yok.", color=0xE74C3C)
    else:
        embed = discord.Embed(
            title="🤖 Komut kaplumbağaya takıldı",
            description="Beklenmedik bir hata oldu. Bu durum bot sahibine bildirildi.",
            color=0xE74C3C,
        )
    try:
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.HTTPException:
        await interaction.followup.send(embed=embed, ephemeral=True)


# --- sahip komutları ---
@bot.tree.command(name="sunucular", description="Botun olduğu sunucuları listele (sahip).")
async def sunucular(interaction: discord.Interaction) -> None:
    if interaction.user.id != db.constants_owner():
        await interaction.response.send_message(embed=discord.Embed(description="❌ Bu komut sahibe özeldir.", color=0xE74C3C), ephemeral=True)
        return
    embed = discord.Embed(
        title="🌐 Sunucular",
        description="\n".join(
            f"• `{g.name}` — {g.member_count} üye" for g in bot.guilds
        ) or "Bot hiçbir sunucuda değil.",
        color=0x00BFFF,
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="kapat", description="Botu kapat (sahip).")
async def kapat(interaction: discord.Interaction) -> None:
    if interaction.user.id != db.constants_owner():
        await interaction.response.send_message(embed=discord.Embed(description="❌ Bu komut sahibe özeldir.", color=0xE74C3C), ephemeral=True)
        return
    await interaction.response.send_message(embed=discord.Embed(description="👋 Kapatılıyorum...", color=0x00BFFF))
    await bot.close()


@bot.tree.command(name="seskur", description="Botu bir ses kanalına bağlar + streaming rozetini açar (sahip).")
async def seskur(interaction: discord.Interaction, kanal: discord.VoiceChannel) -> None:
    if interaction.user.id != db.constants_owner():
        await interaction.response.send_message(embed=discord.Embed(description="❌ Bu komut sahibe özeldir.", color=0xE74C3C), ephemeral=True)
        return
    db.guncelle(interaction.guild.id, ses_kanal_id=kanal.id)
    await interaction.response.defer(ephemeral=True)
    try:
        for ses in kanal.guild.voice_channels:
            if bot.user.id in [m.id for m in ses.members]:
                await ses.guild.voice_client.disconnect()
                break
        await kanal.connect(self_deaf=True)
        await bot.change_presence(
            activity=discord.Streaming(
                name=".gg/supnex",
                url="https://www.twitch.tv/supnex",
            )
        )
        await interaction.followup.send(
            embed=discord.Embed(description=f"🟢 {kanal.mention} kanalına bağlandım.\nRozet: **LIVE / Yayında** (streaming)", color=0x2ECC71),
            ephemeral=True,
        )
    except Exception as hata:
        await interaction.followup.send(
            embed=discord.Embed(description=f"❌ Bağlanamadım: {hata}", color=0xE74C3C),
            ephemeral=True,
        )


@bot.tree.command(name="sestemizle", description="Botu ses kanalından çıkarır ve rozeti kapatır (sahip).")
async def sestemizle(interaction: discord.Interaction) -> None:
    if interaction.user.id != db.constants_owner():
        await interaction.response.send_message(embed=discord.Embed(description="❌ Bu komut sahibe özeldir.", color=0xE74C3C), ephemeral=True)
        return
    db.guncelle(interaction.guild.id, ses_kanal_id=None)
    for ses in interaction.guild.voice_channels:
        if bot.user.id in [m.id for m in ses.members]:
            await ses.guild.voice_client.disconnect()
            break
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=".gg/supnex"))
    await interaction.response.send_message(
        embed=discord.Embed(description="🔴 Sesten çıktım, rozet kapalı.", color=0xF1C40F),
        ephemeral=True,
    )


if __name__ == "__main__":
    if not TOKEN:
        print("supnex :: HATA: .env içinde DISCORD_TOKEN yok.")
        raise SystemExit(1)
    bot.run(TOKEN, reconnect=True)