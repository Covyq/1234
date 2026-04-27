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
    1493199914572972032,
    123456789012345678,
    987654321098765432,
    1477953756225081394,
    831242102179758100
]

# 🔔 НОВОЕ
SKLAD_ROLE_ID = 123456789012345678      # роль @склад
SKLAD_ALERT_CHANNEL_ID = 123456789012345678  # канал для уведомлений

bot = discord.Bot(intents=discord.Intents.all(), debug_guilds=[GUILD_ID])

db = SqliteDatabase("TimerDataBase.db")

CHANNEL_CACHE = {"sklad": {}, "simple": {}, "mpf": {}}

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

    # 🔔 новое поле
    notified = BooleanField(default=False)

db.connect(reuse_if_open=True)
db.create_tables([ChannelConfig, Timer])

# ================= CHANNELS =================
def load_channels():
    global CHANNEL_CACHE
    CHANNEL_CACHE = {"sklad": {}, "simple": {}, "mpf": {}}
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
    return member.guild_permissions.administrator or any(
        r.id in ALLOWED_ROLE_IDS for r in member.roles
    )

# ================= CLEAN =================
def clean_channels():
    for row in ChannelConfig.select():
        guild = bot.get_guild(row.guild_id)
        if not guild or guild.get_channel_or_thread(row.channel_id) is None:
            row.delete_instance()

# ================= VIEWS =================
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
            return await interaction.followup.send("❌ Не найдено", ephemeral=True)

        now_dt = datetime.datetime.now(datetime.timezone.utc)

        # ⏰ 48 ЧАСОВ
        new_end = int((now_dt + datetime.timedelta(hours=48)).timestamp())

        row.time_end = new_end
        row.last_updated_by = interaction.user.id
        row.last_updated_at = int(now_dt.timestamp())
        row.notified = False
        row.save()

        member = interaction.guild.get_member(interaction.user.id)
        nickname = member.display_name if member else "пользователь"

        updated_text = (
            f"{row.text}\n"
            f"⏰ До окончания: <t:{new_end}:R>\n"
            f"🔄 Обновил склад - {nickname}"
        )

        await interaction.message.edit(content=updated_text, view=self)

    async def delete(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return await interaction.followup.send("❌ Только автор", ephemeral=True)

        row.delete_instance()
        await interaction.message.delete()

class SkladExpiredView(View):
    def __init__(self):
        super().__init__(timeout=None)

        btn_delete = Button(label="Удалить склад", style=discord.ButtonStyle.red)
        btn_delete.callback = self.delete
        self.add_item(btn_delete)

    async def delete(self, interaction):
        await interaction.response.defer()

        if not has_access(interaction.user):
            return await interaction.followup.send("❌ Нет доступа", ephemeral=True)

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if row:
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

        member = interaction.guild.get_member(interaction.user.id)
        nickname = member.display_name if member else "пользователь"

        await interaction.message.edit(
            content=interaction.message.content + f"\n📦 Забрал: {nickname}",
            view=self
        )

    async def delete(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return await interaction.followup.send("❌ Только автор", ephemeral=True)

        row.delete_instance()
        await interaction.message.delete()

# ================= LOGIC =================
async def process_expired_timer(t):
    guild = bot.get_guild(t.guild_id)
    if not guild:
        t.delete_instance()
        return

    channel = guild.get_channel_or_thread(t.channel_id)
    if not channel:
        t.delete_instance()
        return

    try:
        msg = await channel.fetch_message(t.message_id)
    except discord.NotFound:
        t.delete_instance()
        return

    member = guild.get_member(t.author)
    nickname = member.display_name if member else "пользователь"
    mention = member.mention if member else "пользователь"

    if t.kind == "sklad":
        await msg.edit(
            content=f"🔥 Склад сгорел!\n👤 {nickname}",
            view=SkladExpiredView()
        )
        t.delete_instance()
        return

    if t.kind == "timer":
        await msg.edit(
            content=f"👤 {mention}\n📌 {t.text}\n✅ Статус: выполнено",
            view=TimerView()
        )
        t.delete_instance()
        return

    if t.kind == "mpf":
        await msg.edit(
            content=f"👤 {nickname}\n📦 Готово",
            view=MPFView(show_take=True)
        )
        t.delete_instance()

# ================= LOOP =================
@tasks.loop(seconds=30)
async def loop():
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    for t in Timer.select():
        try:
            # 🔔 уведомление
            if t.kind == "sklad" and not t.notified and t.time_end - now <= 1800 and t.time_end > now:
                guild = bot.get_guild(t.guild_id)
                if guild:
                    channel = guild.get_channel(SKLAD_ALERT_CHANNEL_ID)
                    role = guild.get_role(SKLAD_ROLE_ID)

                    if channel and role:
                        await channel.send(
                            f"⏰ {role.mention} склад скоро сгорит!\n"
                            f"Осталось <t:{t.time_end}:R>"
                        )

                t.notified = True
                t.save()

            if t.time_end < now:
                await process_expired_timer(t)

        except Exception:
            print(traceback.format_exc())
            t.delete_instance()

# ================= READY =================
@bot.event
async def on_ready():
    print(f"Bot online {bot.user}")
    clean_channels()
    load_channels()
    await loop.start()

# ================= COMMANDS =================
@bot.slash_command(name="setskladchannel", guild_ids=[GUILD_ID])
async def setskladchannel(ctx, channel: discord.TextChannel):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    set_channel(ctx.guild.id, channel.id, "sklad")
    await ctx.respond("✅ склад установлен", ephemeral=True)

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

@bot.slash_command(name="таймер", guild_ids=[GUILD_ID])
async def timer(ctx, название: str, minutes: int):
    channel_id = get_channel(ctx.guild.id, "simple")
    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    end = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)
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
        author=ctx.author.id
    )

@bot.slash_command(name="склад", guild_ids=[GUILD_ID])
async def sklad(ctx, гекс: str, регион: str, склад: str, пароль: str):
    channel_id = get_channel(ctx.guild.id, "sklad")
    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    await ctx.defer()

    # ⏰ 48 часов
    end_ts = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=48)).timestamp())

    text = f"👤 {ctx.author.display_name}\n**Гекс:** {гекс}\n**Регион:** {регион}\n**Склад:** {склад}\n**Пароль:** {пароль}"

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

@bot.slash_command(name="мпф", guild_ids=[GUILD_ID])
async def mpf(ctx, что_поставил: str, ящиков: int, minutes: int):
    channel_id = get_channel(ctx.guild.id, "mpf")
    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    end = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)
    end_ts = int(end.timestamp())

    text = f"👤 {ctx.author.display_name}\n📦 {что_поставил}\n📦 Ящиков: {ящиков}"

    msg = await ctx.send(text, view=MPFView())

    Timer.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        text=text,
        time_end=end_ts,
        author=ctx.author.id,
        kind="mpf",
        boxes=ящиков
    )

# ================= RUN =================
bot.run(os.environ.get("DISCORD_BOT_TOKEN"))
