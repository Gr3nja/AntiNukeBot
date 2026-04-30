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


def now_utc():
    from main import now_utc
    return now_utc()


async def cmd_help(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="AntiNuke Bot — 使用ガイド",
        description="サーバーへのNukeを自動で検知・処罰するBotです。",
        color=discord.Color.blurple(),
        timestamp=now_utc(),
    )
    embed.add_field(
        name="/antinuke",
        value="サーバーの規模を分析し、最適な保護設定を一括で適用します。",
        inline=False,
    )
    embed.add_field(
        name="/setting",
        value="保護・処罰・ホワイトリスト・ログチャンネルを設定します。",
        inline=False,
    )
    embed.add_field(
        name="/help",
        value="このメッセージを表示します。",
        inline=False,
    )
    embed.add_field(
        name="保護対象",
        value="\n".join(f"- {v}" for v in PROTECTION_LABELS.values()),
        inline=True,
    )
    embed.add_field(
        name="処罰方法",
        value="\n".join(f"- {v}" for v in PUNISHMENT_LABELS.values()),
        inline=True,
    )
    embed.set_footer(text="/antinuke と /setting は管理者のみ使用可能です")
    await interaction.response.send_message(embed=embed, ephemeral=True)


async def cmd_invite(interaction: discord.Interaction) -> None:
    from main import bot
    client_id = bot.user.id if bot.user else "1497512770482999368"
    permissions = 1652355050726
    invite_url = f"https://discord.com/oauth2/authorize?client_id={client_id}&permissions={permissions}&integration_type=0&scope=bot"

    embed = discord.Embed(
        title="AntiNuke Bot — 招待",
        description="このBotをサーバーに追加するには、以下のURLをクリックしてください。",
        color=discord.Color.blurple(),
        timestamp=now_utc(),
    )
    embed.add_field(
        name="招待URL",
        value=f"[クリックしてインストール]({invite_url})",
        inline=False,
    )
    embed.add_field(
        name="必要な権限",
        value="管理者 / 監査ログを表示 / メンバーをBan / タイムアウト",
        inline=False,
    )
    await interaction.response.send_message(embed=embed)