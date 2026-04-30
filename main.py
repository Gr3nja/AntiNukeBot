import os
from dotenv import load_dotenv
load_dotenv()

import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import logging
import json
from command import antinuke, setting, help as help_cmd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

TOKEN = os.getenv("DISCORD_TOKEN")
CONFIG_FILE = "guild_configs.json"
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
class GuildConfig:
    def __init__(self):
        self.enabled: bool = True
        self.log_channel_id: int | None = None
        self.whitelist: set[int] = set()
        self.punishment: str = "ban"
        self.timeout_minutes: int = 60
        self.protections: dict[str, bool] = {k: True for k in PROTECTION_LABELS}
        self.thresholds: dict[str, list[int]] = {k: [3, 10] for k in PROTECTION_LABELS}

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "log_channel_id": self.log_channel_id,
            "whitelist": list(self.whitelist),
            "punishment": self.punishment,
            "timeout_minutes": self.timeout_minutes,
            "protections": self.protections,
            "thresholds": self.thresholds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GuildConfig":
        cfg = cls()
        cfg.enabled = data.get("enabled", True)
        cfg.log_channel_id = data.get("log_channel_id")
        cfg.whitelist = set(data.get("whitelist", []))
        cfg.punishment = data.get("punishment", "ban")
        cfg.timeout_minutes = data.get("timeout_minutes", 60)
        saved_protections = data.get("protections", {})
        cfg.protections = {k: saved_protections.get(k, True) for k in PROTECTION_LABELS}
        saved_thresholds = data.get("thresholds", {})
        cfg.thresholds = {k: saved_thresholds.get(k, [3, 10]) for k in PROTECTION_LABELS}
        return cfg
_configs: dict[int, GuildConfig] = {}



def load_configs() -> None:
    global _configs
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                _configs = {int(k): GuildConfig.from_dict(v) for k, v in data.items()}
                log.info(f"Loaded {len(_configs)} guild configs")
        except Exception as e:
            log.error(f"Failed to load configs: {e}")
            _configs = {}

def save_configs() -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v.to_dict() for k, v in _configs.items()}, f, separators=(",", ":"), ensure_ascii=False)
    except Exception as e:
        log.error(f"Failed to save configs: {e}")

def get_config(guild_id: int) -> GuildConfig:
    if guild_id not in _configs:
        _configs[guild_id] = GuildConfig()
    return _configs[guild_id]

_action_log: dict[int, dict[int, dict[str, list[datetime]]]] = defaultdict(
    lambda: defaultdict(lambda: defaultdict(list))
)
_punished: set[tuple[int, int]] = set()

_bot_created_channels: dict[int, set[int]] = defaultdict(set)

_original_server_names: dict[int, str] = {}

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def record_action(guild_id: int, user_id: int, action: str, cfg: GuildConfig) -> int:
    _, window = cfg.thresholds[action]
    cutoff = now_utc() - timedelta(seconds=window)
    bucket = _action_log[guild_id][user_id][action]
    _action_log[guild_id][user_id][action] = [t for t in bucket if t > cutoff]
    _action_log[guild_id][user_id][action].append(now_utc())
    return len(_action_log[guild_id][user_id][action])

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.moderation = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return
    await bot.process_commands(message)

@tasks.loop(seconds=30)
async def update_status() -> None:
    guilds  = len(bot.guilds)
    latency = round(bot.latency * 1000)
    name    = f"/help | {guilds} Servers | {latency}ms"
    await bot.change_presence(activity=discord.Game(name=name))

@update_status.before_loop
async def before_update_status() -> None:
    await bot.wait_until_ready()

async def punish(guild: discord.Guild, user_id: int, reason: str, cfg: GuildConfig) -> None:
    key = (guild.id, user_id)
    if key in _punished:
        return
    _punished.add(key)

    member = guild.get_member(user_id)
    done: list[str] = []

    if cfg.punishment in ("ban", "role_strip") and member:
        try:
            await member.edit(roles=[], reason=f"[AntiNuke] {reason}")
            done.append("ロール剥奪")
        except discord.HTTPException:
            pass

    if cfg.punishment == "ban":
        try:
            await guild.ban(discord.Object(id=user_id), reason=f"[AntiNuke] {reason}", delete_message_days=0)
            done.append("Ban")
        except discord.HTTPException:
            pass
    elif cfg.punishment == "kick" and member:
        try:
            await member.kick(reason=f"[AntiNuke] {reason}")
            done.append("Kick")
        except discord.HTTPException:
            pass
    elif cfg.punishment == "timeout" and member:
        try:
            until = now_utc() + timedelta(minutes=cfg.timeout_minutes)
            await member.timeout(until, reason=f"[AntiNuke] {reason}")
            done.append(f"タイムアウト {cfg.timeout_minutes}分")
        except discord.HTTPException:
            pass

    if cfg.log_channel_id:
        ch = guild.get_channel(cfg.log_channel_id)
        if isinstance(ch, discord.TextChannel):
            embed = discord.Embed(title="AntiNuke — 違反検知", color=discord.Color.red(), timestamp=now_utc())
            embed.add_field(name="ユーザー", value=f"<@{user_id}> (`{user_id}`)", inline=False)
            embed.add_field(name="処罰",     value=" / ".join(done) or "なし",     inline=True)
            embed.add_field(name="理由",     value=reason,                          inline=False)
            try:
                await ch.send(embed=embed)
            except discord.HTTPException:
                pass

async def check_and_punish(guild: discord.Guild, user_id: int, action: str, desc: str) -> None:
    cfg = get_config(guild.id)
    if not cfg.enabled or not cfg.protections.get(action):
        return
    limit, window = cfg.thresholds[action]
    count = record_action(guild.id, user_id, action, cfg)
    if count >= limit:
        await punish(guild, user_id, f"{desc}（{window}秒以内に{count}回）", cfg)

async def fetch_executor(
    guild: discord.Guild,
    action: discord.AuditLogAction,
    target_id: int | None = None,
) -> discord.Member | None:
    cfg = get_config(guild.id)
    for _ in range(3):
        await asyncio.sleep(1)
        try:
            async for entry in guild.audit_logs(limit=5, action=action):
                if (now_utc() - entry.created_at).total_seconds() > 15:
                    break
                if target_id and (not entry.target or entry.target.id != target_id):
                    continue
                if entry.user_id in cfg.whitelist:
                    return None
                member = guild.get_member(entry.user_id)
                if not member or not member.bot:
                    return None
                if member.id == guild.owner_id:
                    return None
                return member
        except discord.NotFound:
            return None
        except discord.Forbidden:
            return None
        except Exception:
            return None
    return None

@bot.event
async def on_ready() -> None:
    await bot.tree.sync()
    load_configs()
    update_status.start()
    log.info("Ready: %s (ID: %s)", bot.user, bot.user.id)

@bot.event
async def on_guild_join(_: discord.Guild) -> None:
    update_status.restart()

@bot.event
async def on_guild_remove(_: discord.Guild) -> None:
    update_status.restart()

@bot.event
async def on_guild_channel_delete(ch: discord.abc.GuildChannel) -> None:
    ex = await fetch_executor(ch.guild, discord.AuditLogAction.channel_delete)
    if ex: await check_and_punish(ch.guild, ex.id, "channel_delete", "チャンネル大量削除")

@bot.event
async def on_guild_channel_create(ch: discord.abc.GuildChannel) -> None:
    cfg = get_config(ch.guild.id)
    if cfg.enabled and cfg.protections.get("channel_create"):
        ex = await fetch_executor(ch.guild, discord.AuditLogAction.channel_create)
        if ex:
            _bot_created_channels[ch.guild.id].add(ch.id)
            await check_and_punish(ch.guild, ex.id, "channel_create", "チャンネル大量作成")

@bot.event
async def on_guild_channel_delete(ch: discord.abc.GuildChannel) -> None:
    cfg = get_config(ch.guild.id)
    if not cfg.enabled or not cfg.protections.get("bot_channel_delete"):
        ex = await fetch_executor(ch.guild, discord.AuditLogAction.channel_delete)
        if ex: await check_and_punish(ch.guild, ex.id, "channel_delete", "チャンネル大量削除")
        return
    
    if ch.id in _bot_created_channels[ch.guild.id]:
        ex = await fetch_executor(ch.guild, discord.AuditLogAction.channel_delete)
        if ex:
            await check_and_punish(ch.guild, ex.id, "bot_channel_delete", "Bot作成チャンネルの大量削除")
    else:
        ex = await fetch_executor(ch.guild, discord.AuditLogAction.channel_delete)
        if ex: await check_and_punish(ch.guild, ex.id, "channel_delete", "チャンネル大量削除")

@bot.event
async def on_guild_role_delete(role: discord.Role) -> None:
    ex = await fetch_executor(role.guild, discord.AuditLogAction.role_delete, role.id)
    if ex: await check_and_punish(role.guild, ex.id, "role_delete", "ロール大量削除")

@bot.event
async def on_guild_role_create(role: discord.Role) -> None:
    ex = await fetch_executor(role.guild, discord.AuditLogAction.role_create, role.id)
    if ex: await check_and_punish(role.guild, ex.id, "role_create", "ロール大量作成")

@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User | discord.Member) -> None:
    ex = await fetch_executor(guild, discord.AuditLogAction.ban, user.id)
    if ex: await check_and_punish(guild, ex.id, "ban", "メンバー大量 Ban")

@bot.event
async def on_member_remove(member: discord.Member) -> None:
    ex = await fetch_executor(member.guild, discord.AuditLogAction.kick, member.id)
    if ex: await check_and_punish(member.guild, ex.id, "kick", "メンバー大量 Kick")

@bot.event
async def on_webhooks_update(ch: discord.abc.GuildChannel) -> None:
    ex = await fetch_executor(ch.guild, discord.AuditLogAction.webhook_create)
    if ex: await check_and_punish(ch.guild, ex.id, "webhook_create", "Webhook 大量作成")

@bot.event
async def on_guild_update(before: discord.Guild, after: discord.Guild) -> None:
    cfg = get_config(after.id)
    if not cfg.enabled:
        return
    
    if before.name != after.name:
        if after.id not in _original_server_names:
            _original_server_names[after.id] = before.name
        
        try:
            async for entry in after.audit_logs(limit=1, action=discord.AuditLogAction.guild_update):
                if (now_utc() - entry.created_at).total_seconds() > 15:
                    break
                member = after.get_member(entry.user_id)
                if member and member.bot:
                    user_actions = _action_log[after.id].get(entry.user_id, {})
                    has_violation = False
                    for action_key in ["channel_delete", "channel_create", "role_delete", "role_create", "ban", "kick", "webhook_create", "bot_channel_delete"]:
                        if action_key in user_actions and len(user_actions[action_key]) >= cfg.thresholds.get(action_key, [3, 10])[0]:
                            has_violation = True
                            break
                    
                    if has_violation:
                        original_name = _original_server_names.get(after.id, before.name)
                        try:
                            await after.edit(name=original_name, reason=f"[AntiNuke] 保護違反Botによるサーバー名変更を元に戻しました")
                            log.info(f"Restored server name for {after.id}: {after.name} -> {original_name}")
                        except discord.HTTPException:
                            pass
                break
        except discord.Forbidden:
            pass
        except Exception:
            pass

def build_overview_embed(guild: discord.Guild) -> discord.Embed:
    cfg    = get_config(guild.id)
    status = "🟢 有効" if cfg.enabled else "🔴 無効"
    log_ch = f"<#{cfg.log_channel_id}>" if cfg.log_channel_id else "未設定"

    embed = discord.Embed(title="AntiNuke — 設定パネル", color=discord.Color.blurple(), timestamp=now_utc())
    embed.add_field(name="ステータス", value=status,                          inline=True)
    embed.add_field(name="処罰方法",   value=PUNISHMENT_LABELS[cfg.punishment], inline=True)
    embed.add_field(name="ログ",       value=log_ch,                           inline=True)

    prot_lines = [
        f"{'🟢' if cfg.protections[k] else '🔴'} {label}\n  └ 検知基準: {cfg.thresholds[k][0]}回 / {cfg.thresholds[k][1]}秒"
        for k, label in PROTECTION_LABELS.items()
    ]
    embed.add_field(name="保護設定", value="\n".join(prot_lines), inline=False)

    wl = ", ".join(f"<@{uid}>" for uid in list(cfg.whitelist)[:5]) or "なし"
    if len(cfg.whitelist) > 5:
        wl += f" 他{len(cfg.whitelist) - 5}人"
    embed.add_field(name="ホワイトリスト", value=wl, inline=False)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.set_footer(text=f"{guild.name} • サーバーID: {guild.id}")
    return embed

class ThresholdModal(discord.ui.Modal, title="検知基準設定"):
    def __init__(self, action_key: str) -> None:
        super().__init__()
        self.action_key = action_key
        self.count_input = discord.ui.TextInput(
            label=f"{PROTECTION_LABELS[action_key]} — 何回で発動しますか？",
            placeholder="例: 3",
            default="3",
            max_length=3,
        )
        self.window_input = discord.ui.TextInput(
            label="何秒以内で発動しますか？",
            placeholder="例: 10",
            default="10",
            max_length=4,
        )
        self.add_item(self.count_input)
        self.add_item(self.window_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            count  = max(1, int(self.count_input.value))
            window = max(1, int(self.window_input.value))
        except ValueError:
            await interaction.response.send_message("数値を入力してください。", ephemeral=True)
            return
        cfg = get_config(interaction.guild_id)
        cfg.thresholds[self.action_key] = [count, window]
        save_configs()
        await interaction.response.send_message(
            f"{PROTECTION_LABELS[self.action_key]} の検知基準を {count}回 / {window}秒 に設定しました。",
            ephemeral=True,
        )


class TimeoutModal(discord.ui.Modal, title="タイムアウト時間設定"):
    minutes_input = discord.ui.TextInput(
        label="タイムアウト時間（分）",
        placeholder="例: 60",
        default="60",
        max_length=4,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            minutes = max(1, int(self.minutes_input.value))
        except ValueError:
            await interaction.response.send_message("正しい数値を入力してください。", ephemeral=True)
            return
        cfg = get_config(interaction.guild_id)
        cfg.timeout_minutes = minutes
        save_configs()
        await interaction.response.send_message(
            f"タイムアウト時間を {minutes}分 に設定しました。",
            ephemeral=True,
        )


class WhitelistAddModal(discord.ui.Modal, title="ホワイトリストに追加"):
    uid_input = discord.ui.TextInput(label="ユーザーID", placeholder="例: 0113581321", max_length=20)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            uid = int(self.uid_input.value)
        except ValueError:
            await interaction.response.send_message("正しいIDを入力してください。", ephemeral=True)
            return
        get_config(interaction.guild_id).whitelist.add(uid)
        save_configs()
        await interaction.response.send_message(f"<@{uid}> をホワイトリストに追加しました。", ephemeral=True)


class WhitelistRemoveModal(discord.ui.Modal, title="ホワイトリストから削除"):
    uid_input = discord.ui.TextInput(label="ユーザーID", placeholder="例: 123456789101112", max_length=20)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            uid = int(self.uid_input.value)
        except ValueError:
            await interaction.response.send_message("正しいIDを入力してください。", ephemeral=True)
            return
        get_config(interaction.guild_id).whitelist.discard(uid)
        save_configs()
        await interaction.response.send_message(f"<@{uid}> をホワイトリストから削除しました。", ephemeral=True)


class LogChannelModal(discord.ui.Modal, title="ログチャンネルを設定"):
    channel_id_input = discord.ui.TextInput(
        label="チャンネルID",
        placeholder="例: 1234567890123456789",
        max_length=20,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            channel_id = int(self.channel_id_input.value)
            channel = interaction.guild.get_channel(channel_id)
            if not channel or not isinstance(channel, discord.TextChannel):
                await interaction.response.send_message("有効なテキストチャンネルが見つかりません。", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("正しいチャンネルIDを入力してください。", ephemeral=True)
            return
        cfg = get_config(interaction.guild_id)
        cfg.log_channel_id = channel_id
        save_configs()
        await interaction.response.send_message(f"ログチャンネルを <#{channel_id}> に設定しました。", ephemeral=True)

class ProtectionView(discord.ui.View):
    def __init__(self, guild: discord.Guild) -> None:
        super().__init__(timeout=180)
        self.guild = guild
        cfg = get_config(guild.id)

        self.toggle_select = discord.ui.Select(
            placeholder="保護設定を選択して ON/OFF を切り替え...",
            options=[
                discord.SelectOption(
                    label=f"{'🟢' if cfg.protections[k] else '🔴'} {label}",
                    value=k,
                    description=f"検知基準: {cfg.thresholds[k][0]}回 / {cfg.thresholds[k][1]}秒"
                )
                for k, label in PROTECTION_LABELS.items()
            ],
            row=0,
        )
        self.toggle_select.callback = self._on_toggle
        self.add_item(self.toggle_select)

        self.threshold_select = discord.ui.Select(
            placeholder="検知基準を変更する項目を選択...",
            options=[discord.SelectOption(label=v, value=k) for k, v in PROTECTION_LABELS.items()],
            row=1,
        )
        self.threshold_select.callback = self._on_threshold_select
        self.add_item(self.threshold_select)

        back = discord.ui.Button(label="戻る", style=discord.ButtonStyle.secondary, row=2)
        back.callback = self._back
        self.add_item(back)

    async def _on_toggle(self, interaction: discord.Interaction) -> None:
        key = self.toggle_select.values[0]
        cfg = get_config(interaction.guild_id)
        cfg.protections[key] ^= True
        save_configs()
        await interaction.response.edit_message(
            embed=build_overview_embed(interaction.guild),
            view=ProtectionView(interaction.guild),
        )

    async def _on_threshold_select(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ThresholdModal(self.threshold_select.values[0]))

    async def _back(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            embed=build_overview_embed(interaction.guild),
            view=MainSettingView(interaction.guild),
        )

class PunishmentView(discord.ui.View):
    def __init__(self, guild: discord.Guild) -> None:
        super().__init__(timeout=180)
        cfg = get_config(guild.id)

        self.select = discord.ui.Select(
            placeholder="処罰方法を選択",
            options=[
                discord.SelectOption(
                    label=v,
                    value=k,
                    default=(cfg.punishment == k)
                )
                for k, v in PUNISHMENT_LABELS.items()
            ],
            row=0,
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

        timeout_btn = discord.ui.Button(label="タイムアウト時間設定", style=discord.ButtonStyle.primary, row=1)
        timeout_btn.callback = self._on_timeout
        self.add_item(timeout_btn)

        back = discord.ui.Button(label="戻る", style=discord.ButtonStyle.secondary, row=1)
        back.callback = self._back
        self.add_item(back)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        cfg = get_config(interaction.guild_id)
        cfg.punishment = self.select.values[0]
        save_configs()
        await interaction.response.edit_message(
            embed=build_overview_embed(interaction.guild),
            view=PunishmentView(interaction.guild),
        )

    async def _on_timeout(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(TimeoutModal())

    async def _back(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            embed=build_overview_embed(interaction.guild),
            view=MainSettingView(interaction.guild),
        )

class WhitelistView(discord.ui.View):
    def __init__(self, guild: discord.Guild) -> None:
        super().__init__(timeout=180)

    @discord.ui.button(label="追加", style=discord.ButtonStyle.success, row=0)
    async def add_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(WhitelistAddModal())

    @discord.ui.button(label="削除", style=discord.ButtonStyle.danger, row=0)
    async def remove_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(WhitelistRemoveModal())

    @discord.ui.button(label="戻る", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=build_overview_embed(interaction.guild),
            view=MainSettingView(interaction.guild),
        )

class MainSettingView(discord.ui.View):
    def __init__(self, guild: discord.Guild) -> None:
        super().__init__(timeout=180)
        cfg = get_config(guild.id)
        self.toggle_btn.label = "無効化" if cfg.enabled else "有効化"
        self.toggle_btn.style = discord.ButtonStyle.danger if cfg.enabled else discord.ButtonStyle.success

    @discord.ui.button(label="保護設定", style=discord.ButtonStyle.primary, row=0)
    async def protection_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        embed = build_overview_embed(interaction.guild)
        embed.title = "AntiNuke — 保護設定"
        await interaction.response.edit_message(embed=embed, view=ProtectionView(interaction.guild))

    @discord.ui.button(label="処罰設定", style=discord.ButtonStyle.primary, row=0)
    async def punishment_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        embed = build_overview_embed(interaction.guild)
        embed.title = "AntiNuke — 処罰設定"
        await interaction.response.edit_message(embed=embed, view=PunishmentView(interaction.guild))

    @discord.ui.button(label="ホワイトリスト", style=discord.ButtonStyle.secondary, row=0)
    async def whitelist_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        embed = build_overview_embed(interaction.guild)
        embed.title = "AntiNuke — ホワイトリスト"
        await interaction.response.edit_message(embed=embed, view=WhitelistView(interaction.guild))

    @discord.ui.button(label="ログチャンネル設定", style=discord.ButtonStyle.primary, row=1)
    async def log_channel_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(LogChannelModal())

    @discord.ui.button(label="placeholder", style=discord.ButtonStyle.danger, row=1)
    async def toggle_btn(self, interaction: discord.Interaction, btn: discord.ui.Button) -> None:
        cfg = get_config(interaction.guild_id)
        cfg.enabled = not cfg.enabled
        btn.label = "無効化" if cfg.enabled else "有効化"
        btn.style = discord.ButtonStyle.danger if cfg.enabled else discord.ButtonStyle.success
        save_configs()
        await interaction.response.edit_message(
            embed=build_overview_embed(interaction.guild), view=self
        )

@bot.tree.command(name="antinuke", description="自動でサーバーのnuke対策を最適に設定します")
@app_commands.default_permissions(administrator=True)
async def cmd_antinuke(interaction: discord.Interaction) -> None:
    from command.antinuke import cmd_antinuke as run_antinuke
    await run_antinuke(interaction)


@bot.tree.command(name="setting", description="基準値・保護対象・処罰などを設定します")
@app_commands.default_permissions(administrator=True)
async def cmd_setting(interaction: discord.Interaction) -> None:
    from command.setting import cmd_setting as run_setting
    await run_setting(interaction)


@bot.tree.command(name="help", description="AntiNuke Botの使用方法を表示します")
async def cmd_help(interaction: discord.Interaction) -> None:
    from command.help import cmd_help as run_help
    await run_help(interaction)


@bot.tree.command(name="invite", description="BotをサーバーにインストールするためのURLを表示します")
async def cmd_invite(interaction: discord.Interaction) -> None:
    from command.help import cmd_invite as run_invite
    await run_invite(interaction)


if __name__ == "__main__":
    bot.run(TOKEN)