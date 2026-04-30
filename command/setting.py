import discord
from discord import app_commands
import logging

log = logging.getLogger(__name__)

PROTECTION_LABELS: dict[str, str] = {
    "channel_delete":    "チャンネル削除",
    "channel_create":   "チャンネル作成",
    "role_delete":       "ロール削除",
    "role_create":       "ロール作成",
    "ban":               "大量 Ban",
    "kick":              "大量 Kick",
    "webhook_create":    "Webhook 作成",
    "bot_channel_delete": "Botによるチャンネル削除",
}

PUNISHMENT_LABELS: dict[str, str] = {
    "ban":        "Ban",
    "kick":       "Kick",
    "timeout":    "タイムアウト",
    "role_strip": "ロール剥奪のみ",
}


def get_config(guild_id: int):
    from main import get_config
    return get_config(guild_id)


def build_overview_embed(guild: discord.Guild):
    from main import build_overview_embed
    return build_overview_embed(guild)


def get_main_view():
    from main import MainSettingView
    return MainSettingView


@discord.app_commands.default_permissions(administrator=True)
async def cmd_setting(interaction: discord.Interaction) -> None:
    MainSettingView = get_main_view()
    await interaction.response.send_message(
        embed=build_overview_embed(interaction.guild),
        view=MainSettingView(interaction.guild),
        ephemeral=True,
    )