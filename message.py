import os
import datetime
import traceback
import discord
from discord.ext import tasks
from discord.ui import View, Button
from peewee import *

# ================= CONFIG =================

GUILD_ID = 1278259070666801214

ALLOWED_ROLE_IDS = [
    1420081710510379079,
    694197038362918923,
    1397716497928949843,
    1397716702242013276,
    475990315623251969,
    422500854910681089,
    1224787828815171595,
    1477953756225081394,
    831242102179758100
]

# роли для /актив
AKTIV_ROLE_IDS = [
    1420081710510379079,  # пример
]

bot = discord.Bot(intents=discord.Intents.all(), debug_guilds=[GUILD_ID])
db = SqliteDatabase("TimerDataBase.db")

CHANNEL_CACHE = {
    "sklad": {},
    "simple": {},
    "mpf": {},
    "sklad_notify": {},
    "aktiv": {}  # NEW
}

# ================= DB =================

class BaseModel(Model):
    class Meta:
        database = db


class ChannelConfig(BaseModel):
    guild_id = BigIntegerField()
    channel_id = BigIntegerField()
    channel_type = TextField()


class Timer(BaseModel):
    guild_id = BigIntegerField()
    channel_id = BigIntegerField()
    message_id = BigIntegerField()
    text = TextField()
    time_end = BigIntegerField()
    author = BigIntegerField()
    kind = TextField(default="timer")

    boxes = IntegerField(null=True)
    taken_by = BigIntegerField(null=True)

    last_updated_by = BigIntegerField(null=True)
    last_updated_at = BigIntegerField(null=True)

    notified_3h = BooleanField(default=False)
    notified_2h = IntegerField(default=0)
    notified_1h = IntegerField(default=0)
    notify_messages = TextField(null=True)
    last_notify_time = BigIntegerField(null=True)


db.connect(reuse_if_open=True)
db.create_tables([ChannelConfig, Timer])

# ================= CHANNELS =================

def load_channels():
    global CHANNEL_CACHE
    CHANNEL_CACHE = {
        "sklad": {},
        "simple": {},
        "mpf": {},
        "sklad_notify": {},
        "aktiv": {}
    }

    for row in ChannelConfig.select():
        CHANNEL_CACHE.setdefault(row.channel_type, {})
        CHANNEL_CACHE[row.channel_type][row.guild_id] = row.channel_id


def set_channel(guild_id, channel_id, channel_type):
    row = ChannelConfig.get_or_none(
        (ChannelConfig.guild_id == guild_id) &
        (ChannelConfig.channel_type == channel_type)
    )

    if row:
        row.channel_id = channel_id
        row.save()
    else:
        ChannelConfig.create(
            guild_id=guild_id,
            channel_id=channel_id,
            channel_type=channel_type
        )

    CHANNEL_CACHE.setdefault(channel_type, {})[guild_id] = channel_id


def get_channel(guild_id, channel_type):
    return CHANNEL_CACHE.get(channel_type, {}).get(guild_id)

# ================= PERMS =================

def has_access(member):
    return (
        member.guild_permissions.administrator or
        any(r.id in ALLOWED_ROLE_IDS for r in member.roles)
    )


def has_aktiv_access(member):
    return (
        member.guild_permissions.administrator or
        any(r.id in AKTIV_ROLE_IDS for r in member.roles)
    )

# ================= CLEAN =================

def clean_channels():
    for row in ChannelConfig.select():
        guild = bot.get_guild(row.guild_id)
        if not guild or guild.get_channel_or_thread(row.channel_id) is None:
            row.delete_instance()

# ================= VIEWS =================
# (оставлены без изменений)

class SkladView(View):
    def __init__(self):
        super().__init__(timeout=None)

        update = Button(label="Обновить склад", style=discord.ButtonStyle.green)
        delete = Button(label="Удалить", style=discord.ButtonStyle.red)

        update.callback = self.update
        delete.callback = self.delete

        self.add_item(update)
        self.add_item(delete)

    async def update(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row:
            return await interaction.followup.send("❌ Не найдено", ephemeral=True)

        now = datetime.datetime.now(datetime.timezone.utc)
        new_end = int((now + datetime.timedelta(hours=48)).timestamp())

        row.time_end = new_end
        row.save()

        await interaction.message.edit(
            content=f"{row.text}\n⏰ До окончания: <t:{new_end}:R>",
            view=self
        )

    async def delete(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return await interaction.followup.send("❌ Только автор", ephemeral=True)

        row.delete_instance()
        await interaction.message.delete()


class TimerView(View):
    def __init__(self):
        super().__init__(timeout=None)
        btn = Button(label="Удалить таймер", style=discord.ButtonStyle.red)
        btn.callback = self.delete
        self.add_item(btn)

    async def delete(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return await interaction.followup.send("❌ Только автор", ephemeral=True)

        row.delete_instance()
        await interaction.message.delete()


class MPFView(View):
    def __init__(self, show_take=False):
        super().__init__(timeout=None)

        delete = Button(label="Удалить таймер", style=discord.ButtonStyle.red)
        delete.callback = self.delete
        self.add_item(delete)

        take = Button(label="Забрал заказ", style=discord.ButtonStyle.green, disabled=not show_take)
        take.callback = self.take
        self.add_item(take)

    async def take(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or row.taken_by:
            return await interaction.followup.send("❌ Уже забрали", ephemeral=True)

        row.taken_by = interaction.user.id
        row.save()

        await interaction.message.edit(
            content=interaction.message.content + f"\n📦 Забрал: {interaction.user.display_name}",
            view=self
        )

    async def delete(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return await interaction.followup.send("❌ Только автор", ephemeral=True)

        row.delete_instance()
        await interaction.message.delete()

# ================= COMMANDS =================

@bot.slash_command(name="setaktivchat", guild_ids=[GUILD_ID])
async def setaktivchat(ctx, channel: discord.TextChannel):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    set_channel(ctx.guild.id, channel.id, "aktiv")
    await ctx.respond("✅ Актив чат установлен", ephemeral=True)


@bot.slash_command(name="актив", guild_ids=[GUILD_ID])
async def aktiv(
    ctx,
    цель: str,
    локация: str,
    нужно: str,
    состояние: str,
    время: str,
    voice_channel: discord.VoiceChannel
):
    channel_id = get_channel(ctx.guild.id, "aktiv")

    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    if not has_aktiv_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    state_map = {
        "критично": ":red_square:",
        "напряжённо": ":orange_square:",
        "стабильно": ":yellow_square:",
        "спокойно": ":green_square:"
    }

    state_emoji = state_map.get(состояние.lower(), "")

    text = (
        f":dart: ЦЕЛЬ: {цель}\n"
        f":round_pushpin: ЛОКАЦИЯ: {локация}\n"
        f":busts_in_silhouette: НУЖНО: {нужно}\n"
        f":package: СОСТОЯНИЕ: {state_emoji} {состояние}\n"
        f":alarm_clock: ВРЕМЯ: {время}\n"
        f"🔊 Канал: {voice_channel.mention}"
    )

    await ctx.send(text)
    await ctx.respond("✅ Актив создан", ephemeral=True)

# ================= СТАРЫЕ КОМАНДЫ =================

@bot.slash_command(name="таймер", guild_ids=[GUILD_ID])
async def timer(ctx, название: str, days: int = 0, hours: int = 0, minutes: int = 0):
    channel_id = get_channel(ctx.guild.id, "simple")

    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    end = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        days=days, hours=hours, minutes=minutes
    )
    end_ts = int(end.timestamp())

    msg = await ctx.send(
        f"👤 {ctx.author.mention}\n📌 {название}\n⏰ <t:{end_ts}:R>",
        view=TimerView()
    )

    Timer.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        text=название,
        time_end=end_ts,
        author=ctx.author.id,
        kind="timer"
    )

    await ctx.respond("✅ таймер создан", ephemeral=True)


@bot.slash_command(name="склад", guild_ids=[GUILD_ID])
async def sklad(ctx, гекс: str, регион: str, склад: str, пароль: str):
    channel_id = get_channel(ctx.guild.id, "sklad")

    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    end_ts = int(
        (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=48)).timestamp()
    )

    text = (
        f"👤 {ctx.author.display_name}\n"
        f"**Гекс:** {гекс}\n"
        f"**Регион:** {регион}\n"
        f"**Склад:** {склад}\n"
        f"**Пароль:** {пароль}"
    )

    msg = await ctx.send(
        f"{text}\n⏰ До окончания: <t:{end_ts}:R>",
        view=SkladView()
    )

    Timer.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        text=text,
        time_end=end_ts,
        author=ctx.author.id,
        kind="sklad"
    )

    await ctx.respond("✅ склад создан", ephemeral=True)


@bot.slash_command(name="мпф", guild_ids=[GUILD_ID])
async def mpf(ctx, что_поставил: str, ящиков: int):
    channel_id = get_channel(ctx.guild.id, "mpf")

    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    text = (
        f"👤 Кто поставил: {ctx.author.display_name}\n"
        f"📦 Что поставил: {что_поставил}\n"
        f"📦 Ящиков: {ящиков}\n"
        f"Статус: ожидание"
    )

    msg = await ctx.send(text, view=MPFView(False))

    Timer.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        text=text,
        time_end=0,
        author=ctx.author.id,
        kind="mpf",
        boxes=ящиков
    )

    await ctx.respond("✅ MPF создан", ephemeral=True)

# ================= RUN =================

@bot.event
async def on_ready():
    print(f"Bot online {bot.user}")
    load_channels()

bot.run(os.environ.get("DISCORD_BOT_TOKEN"))
