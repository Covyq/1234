import os
import datetime
import traceback
import discord
from discord.ext import tasks
from discord.ui import View, Button
from peewee import *

# CONFIG
GUILD_ID = 1278259070666801214

ALLOWED_ROLE_IDS = [
    1493199914572972032,
    123456789012345678,
    987654321098765432,
    1477953756225081394,
    831242102179758100
]

bot = discord.Bot(intents=discord.Intents.all(), debug_guilds=[GUILD_ID])

db = SqliteDatabase("TimerDataBase.db")

CHANNEL_CACHE = {"sklad": {}, "simple": {}, "mpf": {}, "sklad_notify": {}}

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

    # уведомления
    notified_3h = BooleanField(default=False)
    notified_2h_count = IntegerField(default=0)
    notified_1h_count = IntegerField(default=0)
    notification_messages = TextField(null=True)

db.connect(reuse_if_open=True)
db.create_tables([ChannelConfig, Timer])

# ================= CHANNELS =================

def load_channels():
    global CHANNEL_CACHE
    CHANNEL_CACHE = {"sklad": {}, "simple": {}, "mpf": {}, "sklad_notify": {}}
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

# ================= NOTIFY =================

async def send_sklad_notification(t, text):
    notify_channel_id = get_channel(t.guild_id, "sklad_notify")
    if not notify_channel_id:
        return

    guild = bot.get_guild(t.guild_id)
    if not guild:
        return

    channel = guild.get_channel_or_thread(notify_channel_id)
    if not channel:
        return

    msg = await channel.send(text)

    ids = []
    if t.notification_messages:
        ids = t.notification_messages.split(",")

    ids.append(str(msg.id))
    t.notification_messages = ",".join(ids)
    t.save()

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

        btn_update = Button(
            label="Обновить склад",
            style=discord.ButtonStyle.green,
            custom_id="sklad_update"
        )

        btn_delete = Button(
            label="Удалить",
            style=discord.ButtonStyle.red,
            custom_id="sklad_delete"
        )

        btn_update.callback = self.update
        btn_delete.callback = self.delete

        self.add_item(btn_update)
        self.add_item(btn_delete)

    async def update(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row:
            return

        # удаляем уведомления
        if row.notification_messages:
            notify_channel_id = get_channel(row.guild_id, "sklad_notify")
            if notify_channel_id:
                channel = interaction.guild.get_channel_or_thread(notify_channel_id)
                if channel:
                    for msg_id in row.notification_messages.split(","):
                        try:
                            msg = await channel.fetch_message(int(msg_id))
                            await msg.delete()
                        except:
                            pass

        row.notification_messages = None
        row.notified_3h = False
        row.notified_2h_count = 0
        row.notified_1h_count = 0

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        new_end = int((now_dt + datetime.timedelta(hours=48)).timestamp())

        row.time_end = new_end
        row.last_updated_by = interaction.user.id
        row.last_updated_at = int(now_dt.timestamp())
        row.save()

        member = interaction.guild.get_member(interaction.user.id)
        nickname = member.display_name if member else "пользователь"

        await interaction.message.edit(
            content=f"{row.text}\n⏰ До окончания: <t:{new_end}:R>\n🔄 Обновил склад - {nickname}",
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

        btn = Button(
            label="Удалить таймер",
            style=discord.ButtonStyle.red,
            custom_id="timer_delete"
        )

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

        delete = Button(
            label="Удалить таймер",
            style=discord.ButtonStyle.red,
            custom_id="mpf_delete"
        )

        take = Button(
            label="Забрал заказ",
            style=discord.ButtonStyle.green,
            custom_id="mpf_take",
            disabled=not show_take
        )

        delete.callback = self.delete
        take.callback = self.take

        self.add_item(delete)
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
    except:
        t.delete_instance()
        return

    if t.kind == "timer":
        await msg.edit(content=f"👤 <@{t.author}>\n📌 {t.text}\n✅ Статус: выполнено", view=TimerView())

    if t.kind == "mpf":
        await msg.edit(content=f"{t.text}\nСтатус: ✅", view=MPFView(show_take=True))

    if t.kind == "sklad":
        await msg.edit(content=f"{t.text}\n🔥 СГОРЕЛ!", view=None)

    t.delete_instance()

# ================= LOOP =================

@tasks.loop(seconds=30)
async def loop():
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    for t in Timer.select():

        if t.kind == "sklad":
            remaining = t.time_end - now

            if remaining > 0:
                sklad_name = t.text.splitlines()[3].replace("**Склад:** ", "")

                notify_text = (
                    f"@склад Ваш склад {sklad_name} скоро сгорит!\n"
                    f"Пожалуйста, обновите его в игре и обновите его в чате складов!"
                )

                if remaining <= 10800 and not t.notified_3h:
                    await send_sklad_notification(t, notify_text)
                    t.notified_3h = True
                    t.save()

                if remaining <= 7200 and t.notified_2h_count < 2:
                    if now - (t.last_updated_at or 0) >= 1800:
                        await send_sklad_notification(t, notify_text)
                        t.notified_2h_count += 1
                        t.last_updated_at = now
                        t.save()

                if remaining <= 3600 and t.notified_1h_count < 6:
                    if now - (t.last_updated_at or 0) >= 600:
                        await send_sklad_notification(t, notify_text)
                        t.notified_1h_count += 1
                        t.last_updated_at = now
                        t.save()

        if t.time_end < now:
            try:
                await process_expired_timer(t)
            except:
                print(traceback.format_exc())

# ================= READY =================

@bot.event
async def on_ready():
    print(f"Bot online {bot.user}")
    clean_channels()
    load_channels()

    bot.add_view(SkladView())
    bot.add_view(TimerView())
    bot.add_view(MPFView())

    if not loop.is_running():
        loop.start()

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
    await ctx.respond("✅ канал таймера установлен", ephemeral=True)

@bot.slash_command(name="setmpf", guild_ids=[GUILD_ID])
async def setmpf(ctx, channel: discord.TextChannel):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    set_channel(ctx.guild.id, channel.id, "mpf")
    await ctx.respond("✅ канал MPF установлен", ephemeral=True)

@bot.slash_command(name="таймер", guild_ids=[GUILD_ID])
async def timer(ctx, название: str, minutes: int):
    channel_id = get_channel(ctx.guild.id, "simple")
    if ctx.channel.id != channel_id:
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
        author=ctx.author.id,
        kind="timer"
    )

@bot.slash_command(name="мпф", guild_ids=[GUILD_ID])
async def mpf(ctx, что_поставил: str, ящиков: int, minutes: int):
    channel_id = get_channel(ctx.guild.id, "mpf")
    if ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    end = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)
    end_ts = int(end.timestamp())

    text = f"📦 Что поставил: {что_поставил}\n📦 Ящиков: {ящиков}"

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

@bot.slash_command(name="склад", guild_ids=[GUILD_ID])
async def sklad(ctx, гекс: str, регион: str, склад: str, пароль: str):
    channel_id = get_channel(ctx.guild.id, "sklad")
    if ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    end_ts = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=48)).timestamp())

    text = (
        f"👤 {ctx.author.display_name}\n"
        f"**Гекс:** {гекс}\n"
        f"**Регион:** {регион}\n"
        f"**Склад:** {склад}\n"
        f"**Пароль:** {пароль}"
    )

    msg = await ctx.send(
        f"{text}\n⏰ <t:{end_ts}:R>",
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

# ================= RUN =================

bot.run(os.environ.get("DISCORD_BOT_TOKEN"))
