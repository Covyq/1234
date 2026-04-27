import os
import datetime
import discord
from discord.ext import tasks
from discord.ui import View, Button
from peewee import *

# ================= CONFIG =================

GUILD_ID = 1494712012314509372

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

AKTIV_ROLE_IDS = [
    1420081710510379079
]

bot = discord.Bot(intents=discord.Intents.all(), debug_guilds=[GUILD_ID])
db = SqliteDatabase("TimerDataBase.db")

CHANNEL_CACHE = {
    "sklad": {},
    "simple": {},
    "mpf": {},
    "sklad_notify": {},
    "aktiv": {}
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

# ================= VIEWS =================

class AktivModal(discord.ui.Modal):
    def __init__(self, view, emoji, state):
        super().__init__(title=f"{emoji} {state}")
        self.view_ref = view
        self.emoji = emoji
        self.state = state

        self.comment = discord.ui.InputText(
            label="Комментарий",
            placeholder="Введите комментарий...",
            required=True
        )

        self.add_item(self.comment)

    async def callback(self, interaction: discord.Interaction):
        voice_line = interaction.message.content.split("🔊 Канал:")[-1]

        new_text = (
            f"{self.view_ref.base_text}\n"
            f":package: СОСТОЯНИЕ: {self.emoji} {self.state}\n"
            f"💬 Комментарий: {self.comment.value}\n"
            f"🔊 Канал:{voice_line}"
        )

        await interaction.message.edit(content=new_text, view=self.view_ref)
        await interaction.response.send_message("✅ Обновлено", ephemeral=True)


class AktivView(View):
    def __init__(self, author_id, base_text):
        super().__init__(timeout=None)
        self.author_id = author_id
        self.base_text = base_text

    async def update_message(self, interaction, emoji, state):
        await interaction.response.send_modal(
            AktivModal(self, emoji, state)
        )

    @discord.ui.button(label="🟥 Критично", style=discord.ButtonStyle.red)
    async def critical(self, button, interaction):
        await self.update_message(interaction, "🟥", "критично")

    @discord.ui.button(label="🟧 Напряжённо", style=discord.ButtonStyle.secondary)
    async def hard(self, button, interaction):
        await self.update_message(interaction, "🟧", "напряжённо")

    @discord.ui.button(label="🟨 Стабильно", style=discord.ButtonStyle.secondary)
    async def stable(self, button, interaction):
        await self.update_message(interaction, "🟨", "стабильно")

    @discord.ui.button(label="🟩 Спокойно", style=discord.ButtonStyle.green)
    async def calm(self, button, interaction):
        await self.update_message(interaction, "🟩", "спокойно")

    @discord.ui.button(label="Удалить", style=discord.ButtonStyle.red)
    async def delete(self, button, interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ Не твой актив", ephemeral=True)

        await interaction.message.delete()


class SkladView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Обновить склад", style=discord.ButtonStyle.green)
    async def update(self, button, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row:
            return

        now = datetime.datetime.now(datetime.timezone.utc)
        new_end = int((now + datetime.timedelta(hours=48)).timestamp())

        row.time_end = new_end
        row.save()

        await interaction.message.edit(
            content=f"{row.text}\n⏰ До окончания: <t:{new_end}:R>",
            view=self
        )

    @discord.ui.button(label="Удалить", style=discord.ButtonStyle.red)
    async def delete(self, button, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return

        row.delete_instance()
        await interaction.message.delete()


class TimerView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Удалить таймер", style=discord.ButtonStyle.red)
    async def delete(self, button, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return

        row.delete_instance()
        await interaction.message.delete()


class MPFView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Удалить таймер", style=discord.ButtonStyle.red)
    async def delete(self, button, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return

        row.delete_instance()
        await interaction.message.delete()

# ================= COMMANDS =================

@bot.slash_command(name="актив", guild_ids=[GUILD_ID])
async def aktiv(ctx, цель: str, локация: str, нужно: str, voice: discord.VoiceChannel):
    if not has_aktiv_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    channel_id = get_channel(ctx.guild.id, "aktiv")

    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    base_text = (
        f":dart: ЦЕЛЬ: {цель}\n"
        f":round_pushpin: ЛОКАЦИЯ: {локация}\n"
        f":busts_in_silhouette: НУЖНО: {нужно}\n"
        f"🔊 Канал: {voice.mention}"
    )

    view = AktivView(ctx.author.id, base_text)

    await ctx.send(base_text + "\n\nВыберите состояние кнопкой ↓", view=view)
    await ctx.respond("✅ Актив создан", ephemeral=True)


@bot.slash_command(name="таймер", guild_ids=[GUILD_ID])
async def timer(ctx, название: str, hours: int = 1):
    channel_id = get_channel(ctx.guild.id, "simple")

    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    end = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=hours)
    ts = int(end.timestamp())

    msg = await ctx.send(
        f"👤 {ctx.author.mention}\n📌 {название}\n⏰ <t:{ts}:R>",
        view=TimerView()
    )

    Timer.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        text=название,
        time_end=ts,
        author=ctx.author.id
    )

    await ctx.respond("✅ таймер создан", ephemeral=True)


@bot.slash_command(name="мпф", guild_ids=[GUILD_ID])
async def mpf(ctx, что: str, ящиков: int):
    channel_id = get_channel(ctx.guild.id, "mpf")

    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    text = f"👤 {ctx.author.display_name}\n📦 {что}\n📦 Ящиков: {ящиков}"

    msg = await ctx.send(text, view=MPFView())

    Timer.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        text=text,
        time_end=0,
        author=ctx.author.id
    )

    await ctx.respond("✅ MPF создан", ephemeral=True)


@bot.event
async def on_ready():
    print(f"Bot online {bot.user}")
    load_channels()
    bot.add_view(AktivView(0, ""))
    bot.add_view(SkladView())
    bot.add_view(TimerView())
    bot.add_view(MPFView())

bot.run(os.environ.get("DISCORD_BOT_TOKEN"))
