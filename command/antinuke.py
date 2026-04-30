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


def save_configs():
    from main import save_configs
    return save_configs()


def now_utc():
    from main import now_utc
    return now_utc()


@discord.app_commands.default_permissions(administrator=True)
async def cmd_antinuke(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    cfg = get_config(guild.id)

    members = guild.member_count or 1

    if members < 50:
        default_c, default_w = 2, 8
    elif members < 300:
        default_c, default_w = 3, 10
    else:
        default_c, default_w = 5, 15

    for key in cfg.thresholds:
        cfg.thresholds[key] = [default_c, default_w]
    cfg.thresholds["ban"] = [2, 10]
    cfg.thresholds["role_delete"] = [default_c, 8]
    cfg.thresholds["channel_delete"] = [default_c, 8]

    for key in cfg.protections:
        cfg.protections[key] = True
    cfg.enabled = True

    keywords = ("log", "audit", "ログ", "監査", "antinuke", "anti-nuke")
    for ch in guild.text_channels:
        if any(kw in ch.name.lower() for kw in keywords):
            cfg.log_channel_id = ch.id
            break

    save_configs()

    log_txt = f"<#{cfg.log_channel_id}> を自動検出" if cfg.log_channel_id else "未検出  —  /setting で設定してください"

    embed = discord.Embed(
        title="AntiNuke — 自動最適化が完了しました",
        color=discord.Color.green(),
        timestamp=now_utc(),
    )
    embed.add_field(
        name="サーバー分析",
        value=f"メンバー: {members}人  |  チャンネル: {len(guild.channels)}個  |  ロール: {len(guild.roles)}個",
        inline=False,
    )
    embed.add_field(name="標準検知基準", value=f"{default_c}回 / {default_w}秒", inline=True)
    embed.add_field(name="有効な保護", value=f"{len(cfg.protections)}項目 すべて有効", inline=True)
    embed.add_field(name="処罰方法", value=PUNISHMENT_LABELS[cfg.punishment], inline=True)
    embed.add_field(name="ログチャンネル", value=log_txt, inline=False)
    embed.add_field(name="次のステップ", value="/setting で検知基準・処罰・ホワイトリストを調整できます。", inline=False)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    await interaction.followup.send(embed=embed, ephemeral=True)