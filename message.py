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

    CHANNEL_CACHE[channel_type][guild_id] = channel_id

def get_channel(guild_id, channel_type):
    return CHANNEL_CACHE.get(channel_type, {}).get(guild_id)

# ================= PERMS =================

def has_access(member):
    return member.guild_permissions.administrator or any(r.id in ALLOWED_ROLE_IDS for r in member.roles)

def has_aktiv_access(member):
    return member.guild_permissions.administrator or any(r.id in AKTIV_ROLE_IDS for r in member.roles)

# ================= VIEWS =================

class SkladView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Обновить склад", style=discord.ButtonStyle.green)
    async def update(self, button, interaction):
        await interaction.response.defer()

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

    @discord.ui.button(label="Удалить", style=discord.ButtonStyle.red)
    async def delete(self, button, interaction):
        await interaction.response.defer()
        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return

        row.delete_instance()
        await interaction.message.delete()

class AktivView(View):
    def __init__(self, author_id):
        super().__init__(timeout=None)
        self.author_id = author_id

    @discord.ui.button(label="Удалить активность", style=discord.ButtonStyle.danger)
    async def delete(self, button, interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ Не твоя активность", ephemeral=True)

        await interaction.response.defer()
        await interaction.message.delete()

# ================= COMMANDS =================

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

# 🔥 setmpf теперь принимает ID (канал или ветка)
@bot.slash_command(name="setmpf", guild_ids=[GUILD_ID])
async def setmpf(ctx, channel_id: str):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    try:
        channel_id = int(channel_id)
    except:
        return await ctx.respond("❌ Неверный ID", ephemeral=True)

    set_channel(ctx.guild.id, channel_id, "mpf")
    await ctx.respond("✅ MPF канал/ветка установлена", ephemeral=True)

@bot.slash_command(name="setaktivchat", guild_ids=[GUILD_ID])
async def setaktivchat(ctx, channel: discord.TextChannel):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    set_channel(ctx.guild.id, channel.id, "aktiv")
    await ctx.respond("✅ Актив чат установлен", ephemeral=True)

# ===== АКТИВНОСТЬ =====

@bot.slash_command(name="активность", guild_ids=[GUILD_ID])
async def aktivnost(ctx, цель: str, гекс: str, регион: str, количество_людей: int, voice: discord.VoiceChannel):
    if not has_aktiv_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    channel_id = get_channel(ctx.guild.id, "aktiv")
    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    embed = discord.Embed(color=discord.Color.blue())
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    embed.description = f"**{цель}**"
    embed.add_field(name="📍 Локация", value=f"{гекс}, {регион}", inline=False)
    embed.add_field(name="👥 Нужно людей", value=f"{количество_людей}", inline=False)
    embed.add_field(name="", value=f"🔊 {voice.mention}", inline=False)

    await ctx.send(embed=embed, view=AktivView(ctx.author.id))
    await ctx.respond("✅ Активность создана", ephemeral=True)

# ===== ТАЙМЕР =====

@bot.slash_command(name="таймер", guild_ids=[GUILD_ID])
async def timer(ctx, название: str, дни: int = 0, часы: int = 0, минуты: int = 0):
    await ctx.defer(ephemeral=True)

    channel_id = get_channel(ctx.guild.id, "simple")
    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.followup.send("❌ не тот канал", ephemeral=True)

    total_seconds = дни*86400 + часы*3600 + минуты*60
    if total_seconds <= 0:
        return await ctx.followup.send("❌ укажи время", ephemeral=True)

    end = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=total_seconds)
    ts = int(end.timestamp())

    msg = await ctx.channel.send(f"👤 {ctx.author.mention}\n📌 {название}\n⏰ <t:{ts}:R>", view=TimerView())

    Timer.create(ctx.guild.id, ctx.channel.id, msg.id, название, ts, ctx.author.id)
    await ctx.followup.send("✅ таймер создан", ephemeral=True)

# ===== СКЛАД =====

@bot.slash_command(name="склад", guild_ids=[GUILD_ID])
async def sklad(ctx, гекс: str, регион: str, склад: str, пароль: str):
    await ctx.defer(ephemeral=True)

    channel_id = get_channel(ctx.guild.id, "sklad")
    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.followup.send("❌ не тот канал", ephemeral=True)

    end_ts = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=48)).timestamp())

    text = f"👤 {ctx.author.display_name}\n**Гекс:** {гекс}\n**Регион:** {регион}\n**Склад:** {склад}\n**Пароль:** {пароль}"
    msg = await ctx.channel.send(f"{text}\n⏰ <t:{end_ts}:R>", view=SkladView())

    Timer.create(ctx.guild.id, ctx.channel.id, msg.id, text, end_ts, ctx.author.id)
    await ctx.followup.send("✅ склад создан", ephemeral=True)

# ===== MPF =====

@bot.slash_command(name="мпф", guild_ids=[GUILD_ID])
async def mpf(ctx, что: str, ящиков: int, дни: int = 0, часы: int = 0, минуты: int = 0):
    await ctx.defer(ephemeral=True)

    channel_id = get_channel(ctx.guild.id, "mpf")
    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.followup.send("❌ не тот канал", ephemeral=True)

    total_seconds = дни*86400 + часы*3600 + минуты*60
    ts = 0
    time_text = ""

    if total_seconds > 0:
        end = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=total_seconds)
        ts = int(end.timestamp())
        time_text = f"\n⏰ <t:{ts}:R>"

    text = f"👤 {ctx.author.display_name}\n📦 {что}\n📦 Ящиков: {ящиков}{time_text}"
    msg = await ctx.channel.send(text, view=MPFView())

    Timer.create(ctx.guild.id, ctx.channel.id, msg.id, text, ts, ctx.author.id)
    await ctx.followup.send("✅ MPF создан", ephemeral=True)

# ================= START =================

@bot.event
async def on_ready():
    print(f"Bot online {bot.user}")
    load_channels()

bot.run(os.environ.get("DISCORD_BOT_TOKEN"))
