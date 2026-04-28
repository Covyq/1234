import os
import datetime
import traceback
import discord
from discord.ext import tasks
from discord.ui import View, Button
from peewee import *

# ================= CONFIG =================

GUILD_ID = 1494712012314509372

ALLOWED_ROLE_IDS = [
    1493199914572972032,
    123456789012345678,
    987654321098765432,
    1477953756225081394,
    831242102179758100
]

AKTIV_ROLE_IDS = [
    111111111111111111,
    222222222222222222
]

bot = discord.Bot(intents=discord.Intents.all(), debug_guilds=[GUILD_ID])
db = SqliteDatabase("TimerDataBase.db")

CHANNEL_CACHE = {"sklad": {}, "simple": {}, "mpf": {}, "aktiv": {}}

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

db.connect(reuse_if_open=True)
db.create_tables([ChannelConfig, Timer])

# ================= CHANNEL SYSTEM =================

def load_channels():
    global CHANNEL_CACHE
    CHANNEL_CACHE = {"sklad": {}, "simple": {}, "mpf": {}, "aktiv": {}}
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

# ================= PERMISSIONS =================

def has_access(member):
    return member.guild_permissions.administrator or any(
        r.id in ALLOWED_ROLE_IDS for r in member.roles
    )

def has_aktiv_access(member):
    return any(r.id in AKTIV_ROLE_IDS for r in member.roles)

# ================= CLEAN =================

def clean_channels():
    for row in ChannelConfig.select():
        guild = bot.get_guild(row.guild_id)
        if not guild or not guild.get_channel_or_thread(row.channel_id):
            row.delete_instance()

# ================= VIEWS =================

class AktivView(View):
    def __init__(self, author_id=0):
        super().__init__(timeout=None)
        self.author_id = author_id

        btn = Button(label="Удалить активность", style=discord.ButtonStyle.red)
        btn.callback = self.delete
        self.add_item(btn)

    async def delete(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row:
            return

        if (
            interaction.user.id != row.author and
            not any(r.id in ALLOWED_ROLE_IDS for r in interaction.user.roles)
        ):
            return await interaction.followup.send("❌ Нет прав", ephemeral=True)

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
            return
        row.delete_instance()
        await interaction.message.delete()

class SkladView(View):
    def __init__(self):
        super().__init__(timeout=None)

        btn_update = Button(label="Обновить склад", style=discord.ButtonStyle.green)
        btn_delete = Button(label="Удалить", style=discord.ButtonStyle.red)

        btn_update.callback = self.update
        btn_delete.callback = self.delete

        self.add_item(btn_update)
        self.add_item(btn_delete)

    async def update(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row:
            return

        new_end = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=48)).timestamp())
        row.time_end = new_end
        row.save()

        await interaction.message.edit(
            content=f"{row.text}\n\n⏰ <t:{new_end}:R>",
            view=self
        )

    async def delete(self, interaction):
        await interaction.response.defer()
        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return
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
            return

        row.taken_by = interaction.user.id
        row.save()

        await interaction.message.edit(
            content=interaction.message.content + f"\n\n📦 Забрал: {interaction.user.display_name}",
            view=self
        )

    async def delete(self, interaction):
        await interaction.response.defer()
        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return
        row.delete_instance()
        await interaction.message.delete()

# ================= LOOP =================

@tasks.loop(seconds=30)
async def loop():
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    for t in Timer.select():
        try:
            if t.kind == "aktiv":
                continue

            if t.time_end > now:
                continue

            guild = bot.get_guild(t.guild_id)
            if not guild:
                t.delete_instance()
                continue

            channel = guild.get_channel_or_thread(t.channel_id)
            if not channel:
                t.delete_instance()
                continue

            try:
                msg = await channel.fetch_message(t.message_id)
            except:
                t.delete_instance()
                continue

            member = guild.get_member(t.author)
            nickname = member.display_name if member else "пользователь"
            mention = member.mention if member else "пользователь"

            if t.kind == "timer":
                await msg.edit(
                    content=f"👤 {mention}\n📌 {t.text}\n✅ Завершено",
                    view=TimerView()
                )
                t.time_end = now + 10**9
                t.save()

            elif t.kind == "mpf":
                item = t.text.split("📦 Что поставил: ")[1].splitlines()[0]
                await msg.edit(
                    content=(
                        f"👤 {nickname}\n"
                        f"📦 {item}\n"
                        f"📦 Ящиков: {t.boxes}\n"
                        f"Статус: ✅"
                    ),
                    view=MPFView(show_take=True)
                )
                t.time_end = now + 10**9
                t.save()

            elif t.kind == "sklad":
                await msg.edit(
                    content=f"✅ Склад завершён {nickname}",
                    view=None
                )
                t.delete_instance()

        except:
            print(traceback.format_exc())
            t.delete_instance()

# ================= READY =================

@bot.event
async def on_ready():
    print(f"Bot online {bot.user}")
    clean_channels()
    load_channels()

    bot.add_view(TimerView())
    bot.add_view(SkladView())
    bot.add_view(MPFView())
    bot.add_view(AktivView())

    if not loop.is_running():
        loop.start()

# ================= COMMANDS =================

@bot.slash_command(name="setaktivchat", guild_ids=[GUILD_ID])
async def setaktivchat(ctx, channel: discord.TextChannel):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)
    set_channel(ctx.guild.id, channel.id, "aktiv")
    await ctx.respond("✅ чат активности установлен", ephemeral=True)

@bot.slash_command(name="setsimpletimer", guild_ids=[GUILD_ID])
async def setsimpletimer(ctx, channel: discord.TextChannel):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)
    set_channel(ctx.guild.id, channel.id, "simple")
    await ctx.respond("✅ канал таймера установлен", ephemeral=True)

@bot.slash_command(name="setmpf", guild_ids=[GUILD_ID])
async def setmpf(ctx, channel: discord.TextChannel):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)
    set_channel(ctx.guild.id, channel.id, "mpf")
    await ctx.respond("✅ MPF канал установлен", ephemeral=True)

@bot.slash_command(name="setskladchannel", guild_ids=[GUILD_ID])
async def setskladchannel(ctx, channel: discord.TextChannel):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)
    set_channel(ctx.guild.id, channel.id, "sklad")
    await ctx.respond("✅ склад канал установлен", ephemeral=True)

# ===== АКТИВНОСТЬ =====

@bot.slash_command(name="активность", guild_ids=[GUILD_ID])
async def aktiv(ctx, название: str, гекс: str, регион: str, нужно_людей: str, голосовой_канал: discord.VoiceChannel):
    if not has_aktiv_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    channel_id = get_channel(ctx.guild.id, "aktiv")
    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    now_ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    text = (
        f"👤 {ctx.author.display_name}\n\n"
        f"📍 {гекс}, {регион}\n\n"
        f"👥 Нужно: {нужно_людей}\n\n"
        f"🔊 {голосовой_канал.mention}\n\n"
        f"🕒 <t:{now_ts}:R>"
    )

    msg = await ctx.send(text, view=AktivView(ctx.author.id))

    Timer.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        text=text,
        time_end=now_ts + 10**9,
        author=ctx.author.id,
        kind="aktiv"
    )

    await ctx.respond("✅ активность создана", ephemeral=True)

# ===== ТАЙМЕР =====

@bot.slash_command(name="таймер", guild_ids=[GUILD_ID])
async def timer(ctx, название: str, minutes: int):
    channel_id = get_channel(ctx.guild.id, "simple")
    if ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    end = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)).timestamp())

    msg = await ctx.send(
        f"👤 {ctx.author.mention}\n📌 {название}\n⏰ <t:{end}:R>",
        view=TimerView()
    )

    Timer.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        text=название,
        time_end=end,
        author=ctx.author.id,
        kind="timer"
    )

    await ctx.respond("✅ таймер создан", ephemeral=True)

# ===== СКЛАД =====

@bot.slash_command(name="склад", guild_ids=[GUILD_ID])
async def sklad(ctx, гекс: str, регион: str, склад: str, пароль: str):
    channel_id = get_channel(ctx.guild.id, "sklad")
    if channel_id and ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    end_ts = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=48)).timestamp())

    text = (
        f"👤 {ctx.author.display_name}\n"
        f"Гекс: {гекс}\n"
        f"Регион: {регион}\n"
        f"Склад: {склад}\n"
        f"Пароль: {пароль}"
    )

    msg = await ctx.send(f"{text}\n\n⏰ <t:{end_ts}:R>", view=SkladView())

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

# ===== MPF =====

@bot.slash_command(name="мпф", guild_ids=[GUILD_ID])
async def mpf(ctx, что_поставил: str, ящиков: int, minutes: int):
    channel_id = get_channel(ctx.guild.id, "mpf")
    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    end = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)).timestamp())

    text = (
        f"👤 Кто поставил: {ctx.author.display_name}\n"
        f"📦 Что поставил: {что_поставил}\n"
        f"📦 Ящиков: {ящиков}\n"
        f"⏰ <t:{end}:R>\n"
        f"Статус: ожидание"
    )

    msg = await ctx.send(text, view=MPFView(show_take=False))

    Timer.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        text=text,
        time_end=end,
        author=ctx.author.id,
        kind="mpf",
        boxes=ящиков
    )

    await ctx.respond("✅ MPF создан", ephemeral=True)

# ================= RUN =================

bot.run(os.environ.get("DISCORD_BOT_TOKEN"))
