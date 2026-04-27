import os
import datetime
import discord
from discord.ui import View
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

db.connect(reuse_if_open=True)
db.create_tables([ChannelConfig, Timer])

# ================= CHANNELS =================

def load_channels():
    global CHANNEL_CACHE
    CHANNEL_CACHE = {"sklad": {}, "simple": {}, "mpf": {}, "sklad_notify": {}, "aktiv": {}}
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
        ChannelConfig.create(guild_id=guild_id, channel_id=channel_id, channel_type=channel_type)

    CHANNEL_CACHE.setdefault(channel_type, {})[guild_id] = channel_id


def get_channel(guild_id, channel_type):
    return CHANNEL_CACHE.get(channel_type, {}).get(guild_id)

# ================= PERMS =================

def has_access(member):
    return member.guild_permissions.administrator or any(r.id in ALLOWED_ROLE_IDS for r in member.roles)


def has_aktiv_access(member):
    return member.guild_permissions.administrator or any(r.id in AKTIV_ROLE_IDS for r in member.roles)

# ================= АКТИВ =================

class AktivModal(discord.ui.Modal):
    def __init__(self, view, emoji, state):
        super().__init__(title=f"{emoji} {state}")
        self.view_ref = view
        self.emoji = emoji
        self.state = state

        self.comment = discord.ui.InputText(label="Комментарий", required=True)
        self.add_item(self.comment)

    async def callback(self, interaction):
        new_text = (
            f"{self.view_ref.base_text}\n"
            f":package: СОСТОЯНИЕ: {self.emoji} {self.state}\n"
            f"💬 Комментарий: {self.comment.value}"
        )
        await interaction.message.edit(content=new_text, view=self.view_ref)
        await interaction.response.send_message("✅ Обновлено", ephemeral=True)


class AktivView(View):
    def __init__(self, author_id, base_text):
        super().__init__(timeout=None)
        self.author_id = author_id
        self.base_text = base_text

    async def open_modal(self, interaction, emoji, state):
        await interaction.response.send_modal(AktivModal(self, emoji, state))

    @discord.ui.button(label="🟥 Критично", style=discord.ButtonStyle.red, custom_id="aktiv_critical")
    async def critical(self, button, interaction):
        await self.open_modal(interaction, "🟥", "критично")

    @discord.ui.button(label="🟧 Напряжённо", style=discord.ButtonStyle.secondary, custom_id="aktiv_hard")
    async def hard(self, button, interaction):
        await self.open_modal(interaction, "🟧", "напряжённо")

    @discord.ui.button(label="🟨 Стабильно", style=discord.ButtonStyle.secondary, custom_id="aktiv_stable")
    async def stable(self, button, interaction):
        await self.open_modal(interaction, "🟨", "стабильно")

    @discord.ui.button(label="🟩 Спокойно", style=discord.ButtonStyle.green, custom_id="aktiv_calm")
    async def calm(self, button, interaction):
        await self.open_modal(interaction, "🟩", "спокойно")

    @discord.ui.button(label="Удалить", style=discord.ButtonStyle.red, custom_id="aktiv_delete")
    async def delete(self, button, interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ Не твой актив", ephemeral=True)
        await interaction.message.delete()


class AktivCreateView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Создать актив", style=discord.ButtonStyle.green, custom_id="create_aktiv")
    async def create_aktiv(self, button, interaction):
        if not has_aktiv_access(interaction.user):
            return await interaction.response.send_message("❌ Нет прав", ephemeral=True)
        await interaction.response.send_modal(AktivCreateModal())


class AktivCreateModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Создание актива")

        self.goal = discord.ui.InputText(label="Цель")
        self.location = discord.ui.InputText(label="Локация")
        self.need = discord.ui.InputText(label="Нужно")
        self.voice_id = discord.ui.InputText(label="ID голосового канала")

        self.add_item(self.goal)
        self.add_item(self.location)
        self.add_item(self.need)
        self.add_item(self.voice_id)

    async def callback(self, interaction):
        channel_id = get_channel(interaction.guild.id, "aktiv")

        if not channel_id or interaction.channel.id != channel_id:
            return await interaction.response.send_message("❌ не тот канал", ephemeral=True)

        try:
            voice = interaction.guild.get_channel(int(self.voice_id.value))
        except:
            return await interaction.response.send_message("❌ неверный ID", ephemeral=True)

        base_text = (
            f":dart: ЦЕЛЬ: {self.goal.value}\n"
            f":round_pushpin: ЛОКАЦИЯ: {self.location.value}\n"
            f":busts_in_silhouette: НУЖНО: {self.need.value}\n"
            f"🔊 Канал: {voice.mention if voice else 'не найден'}"
        )

        await interaction.channel.send(base_text + "\n\nВыберите состояние ↓", view=AktivView(interaction.user.id, base_text))
        await interaction.response.send_message("✅ Актив создан", ephemeral=True)

# ================= OTHER VIEWS =================

class SkladView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Обновить склад", style=discord.ButtonStyle.green, custom_id="sklad_update")
    async def update(self, button, interaction):
        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row:
            return

        new_end = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=48)).timestamp())
        row.time_end = new_end
        row.save()

        await interaction.message.edit(
            content=f"{row.text}\n⏰ До окончания: <t:{new_end}:R>",
            view=self
        )

    @discord.ui.button(label="Удалить", style=discord.ButtonStyle.red, custom_id="sklad_delete")
    async def delete(self, button, interaction):
        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return
        row.delete_instance()
        await interaction.message.delete()


class TimerView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Удалить таймер", style=discord.ButtonStyle.red, custom_id="timer_delete")
    async def delete(self, button, interaction):
        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return
        row.delete_instance()
        await interaction.message.delete()


class MPFView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Удалить", style=discord.ButtonStyle.red, custom_id="mpf_delete")
    async def delete(self, button, interaction):
        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return
        row.delete_instance()
        await interaction.message.delete()

# ================= COMMANDS =================

@bot.slash_command(name="aktivpanel", guild_ids=[GUILD_ID])
async def aktivpanel(ctx):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)
    await ctx.send("Панель актива ↓", view=AktivCreateView())
    await ctx.respond("✅ Панель отправлена", ephemeral=True)


@bot.slash_command(name="setskladchannel", guild_ids=[GUILD_ID])
async def setskladchannel(ctx, sklad_channel: discord.TextChannel, notify_channel: discord.TextChannel):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    set_channel(ctx.guild.id, sklad_channel.id, "sklad")
    set_channel(ctx.guild.id, notify_channel.id, "sklad_notify")

    await ctx.respond("✅ каналы установлены", ephemeral=True)


@bot.slash_command(name="setsimpletimer", guild_ids=[GUILD_ID])
async def setsimpletimer(ctx, channel: discord.TextChannel):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    set_channel(ctx.guild.id, channel.id, "simple")
    await ctx.respond("✅ таймер установлен", ephemeral=True)


@bot.slash_command(name="setmpf", guild_ids=[GUILD_ID])
async def setmpf(ctx, channel: discord.TextChannel):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    set_channel(ctx.guild.id, channel.id, "mpf")
    await ctx.respond("✅ MPF установлен", ephemeral=True)


@bot.slash_command(name="setaktivchat", guild_ids=[GUILD_ID])
async def setaktivchat(ctx, channel: discord.TextChannel):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    set_channel(ctx.guild.id, channel.id, "aktiv")
    await ctx.respond("✅ Актив чат установлен", ephemeral=True)


@bot.slash_command(name="таймер", guild_ids=[GUILD_ID])
async def timer(ctx, название: str, hours: int = 1):
    channel_id = get_channel(ctx.guild.id, "simple")
    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    ts = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=hours)).timestamp())

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


@bot.slash_command(name="склад", guild_ids=[GUILD_ID])
async def sklad(ctx, гекс: str, регион: str, склад: str, пароль: str):
    channel_id = get_channel(ctx.guild.id, "sklad")

    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    end_ts = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=48)).timestamp())

    text = (
        f"👤 {ctx.author.display_name}\n"
        f"**Гекс:** {гекс}\n"
        f"**Регион:** {регион}\n"
        f"**Склад:** {склад}\n"
        f"**Пароль:** {пароль}"
    )

    msg = await ctx.send(f"{text}\n⏰ До окончания: <t:{end_ts}:R>", view=SkladView())

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
        author=ctx.author.id,
        kind="mpf"
    )

    await ctx.respond("✅ MPF создан", ephemeral=True)

# ================= READY =================

@bot.event
async def on_ready():
    print(f"Bot online {bot.user}")

    load_channels()

    bot.add_view(AktivView(0, ""))
    bot.add_view(AktivCreateView())
    bot.add_view(SkladView())
    bot.add_view(TimerView())
    bot.add_view(MPFView())

bot.run(os.environ.get("DISCORD_BOT_TOKEN"))
