"""Sayfalı görünüm."""
import discord

from . import embeds


class Sayfalayici(discord.ui.View):
    def __init__(self, sayfalar: list[discord.Embed], sahip_id: int) -> None:
        super().__init__()
        self.sayfalar = sayfalar
        self.sahip_id = sahip_id
        self.index = 0
        self._guncelle()

    def _guncelle(self) -> None:
        self.geri.disabled = self.index == 0
        self.ileri.disabled = self.index == len(self.sayfalar) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.sahip_id:
            await interaction.response.send_message(
                embed=embeds.hata("Bu menü senin değil, şef."), ephemeral=True
            )
            return False
        return True

    @discord.ui.button(emoji="◀", style=discord.ButtonStyle.secondary)
    async def geri(self, interaction: discord.Interaction, _) -> None:
        self.index -= 1
        self._guncelle()
        await interaction.response.edit_message(embed=self.sayfalar[self.index], view=self)

    @discord.ui.button(emoji="▶", style=discord.ButtonStyle.secondary)
    async def ileri(self, interaction: discord.Interaction, _) -> None:
        self.index += 1
        self._guncelle()
        await interaction.response.edit_message(embed=self.sayfalar[self.index], view=self)