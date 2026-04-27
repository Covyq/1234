import os
import datetime
import traceback
import discord
from discord.ext import tasks
from discord.ui import View, Button
from peewee import *

# ================= CONFIG =================

GUILD_ID = 419565206335651840

ALLOWED_ROLE_IDS = [
    1420081710510379079,
    694197038362918923,
    1397716702242013276,
    422500854910681089,
    1224787828815171595,
    1477953756225081394,
    831242102179758100,
]

bot = discord.Bot(intents=discord.Intents.all(), debug_guilds=[GUILD_ID])
db = SqliteDatabase("TimerDataBase.db")

CHANNEL_CACHE = {
    "sklad": {},
    "simple": {},
    "mpf": {},
    "sklad_notify": {}
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

    # уведомления
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
        "sklad_notify": {}
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

# ================= CLEAN =================

def clean_channels():
    for row in ChannelConfig.select():
        guild = bot.get_guild(row.guild_id)
        if not guild or guild.get_channel_or_thread(row.channel_id) is None:
            row.delete_instance()

# ================= NOTIFICATIONS =================

async def send_sklad_notification(t):
    guild = bot.get_guild(t.guild_id)
    if not guild:
        return

    notify_channel_id = get_channel(t.guild_id, "sklad_notify")
    if not notify_channel_id:
        return

    channel = guild.get_channel_or_thread(notify_channel_id)
    if not channel:
        return

    sklad_name = t.text.split("**Склад:** ")[1].splitlines()[0]

    msg = await channel.send(
        f"@склад Ваш склад **{sklad_name}** скоро сгорит! "
        f"Пожалуйста, обновите его в игре и обновите его в чате складов!"
    )

    ids = []
    if t.notify_messages:
        ids = t.notify_messages.split(",")

    ids.append(str(msg.id))
    t.notify_messages = ",".join(ids)
    t.save()


async def delete_notifications(t, guild):
    if not t.notify_messages:
        return

    notify_channel_id = get_channel(t.guild_id, "sklad_notify")
    if not notify_channel_id:
        return

    channel = guild.get_channel_or_thread(notify_channel_id)
    if not channel:
        return

    for msg_id in t.notify_messages.split(","):
        try:
            msg = await channel.fetch_message(int(msg_id))
            await msg.delete()
        except:
            pass

    t.notify_messages = None
    t.notified_3h = False
    t.notified_2h = 0
    t.notified_1h = 0
    t.last_notify_time = None
    t.save()

# ================= VIEWS =================

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

        await delete_notifications(row, interaction.guild)

        now = datetime.datetime.now(datetime.timezone.utc)
        new_end = int((now + datetime.timedelta(hours=48)).timestamp())

        row.time_end = new_end
        row.last_updated_by = interaction.user.id
        row.last_updated_at = int(now.timestamp())
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

        await delete_notifications(row, interaction.guild)
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

    if t.kind == "sklad":
        await delete_notifications(t, guild)

        await msg.edit(
            content=f"{t.text}\n🔥 Склад сгорел!",
            view=None
        )
        t.delete_instance()
        return

    if t.kind == "timer":
        await msg.edit(
            content=f"👤 <@{t.author}>\n📌 {t.text}\n✅ Статус: выполнено",
            view=TimerView()
        )
        return

    if t.kind == "mpf":
        await msg.edit(
            content=f"{t.text}\n✅ Статус: готово",
            view=MPFView(True)
        )
        return

# ================= RESTORE =================

async def restore_messages():
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    for t in Timer.select():
        try:
            guild = bot.get_guild(t.guild_id)
            if not guild:
                continue

            channel = guild.get_channel_or_thread(t.channel_id)
            if not channel:
                continue

            try:
                msg = await channel.fetch_message(t.message_id)
            except discord.NotFound:
                t.delete_instance()
                continue

            if t.time_end < now:
                await process_expired_timer(t)
                continue

            if t.kind == "sklad":
                await msg.edit(
                    content=f"{t.text}\n⏰ До окончания: <t:{t.time_end}:R>",
                    view=SkladView()
                )

            elif t.kind == "timer":
                await msg.edit(
                    content=f"👤 <@{t.author}>\n📌 {t.text}\n⏰ <t:{t.time_end}:R>",
                    view=TimerView()
                )

            elif t.kind == "mpf":
                await msg.edit(
                    content=t.text,
                    view=MPFView(False)
                )

        except:
            print(traceback.format_exc())

# ================= LOOP =================

@tasks.loop(seconds=30)
async def loop():
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    for t in Timer.select():
        try:
            if t.kind == "sklad":
                remaining = t.time_end - now

                if remaining <= 10800 and not t.notified_3h:
                    await send_sklad_notification(t)
                    t.notified_3h = True
                    t.last_notify_time = now
                    t.save()

                elif remaining <= 7200 and t.notified_2h < 2:
                    if not t.last_notify_time or now - t.last_notify_time >= 1800:
                        await send_sklad_notification(t)
                        t.notified_2h += 1
                        t.last_notify_time = now
                        t.save()

                elif remaining <= 3600 and t.notified_1h < 6:
                    if not t.last_notify_time or now - t.last_notify_time >= 600:
                        await send_sklad_notification(t)
                        t.notified_1h += 1
                        t.last_notify_time = now
                        t.save()

            if t.time_end < now:
                await process_expired_timer(t)

        except:
            print(traceback.format_exc())

# ================= EVENTS =================

@bot.event
async def on_ready():
    print(f"Bot online {bot.user}")

    clean_channels()
    load_channels()

    bot.add_view(SkladView())
    bot.add_view(TimerView())
    bot.add_view(MPFView())

    await restore_messages()

    if not loop.is_running():
        loop.start()


@bot.event
async def on_raw_message_delete(payload):
    try:
        Timer.delete().where(
            (Timer.message_id == payload.message_id) &
            (Timer.channel_id == payload.channel_id)
        ).execute()
    except:
        print(traceback.format_exc())

# ================= COMMANDS =================

@bot.slash_command(name="setskladchannel", guild_ids=[GUILD_ID])
async def setskladchannel(ctx, sklad_channel: discord.TextChannel, notify_channel: discord.TextChannel):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    set_channel(ctx.guild.id, sklad_channel.id, "sklad")
    set_channel(ctx.guild.id, notify_channel.id, "sklad_notify")

    await ctx.respond("✅ каналы установлены", ephemeral=True)


@bot.slash_command(name="setsimpletimer", guild_ids=[GUILD_ID])
async def setsimpletimer(ctx, channel: discord.TextChannel = None, thread_id: str = None):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    target_id = channel.id if channel else int(thread_id)
    set_channel(ctx.guild.id, target_id, "simple")

    await ctx.respond("✅ таймер установлен", ephemeral=True)


@bot.slash_command(name="setmpf", guild_ids=[GUILD_ID])
async def setmpf(ctx, channel: discord.TextChannel = None, thread_id: str = None):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    target_id = channel.id if channel else int(thread_id)
    set_channel(ctx.guild.id, target_id, "mpf")

    await ctx.respond("✅ MPF установлен", ephemeral=True)


@bot.slash_command(name="таймер", guild_ids=[GUILD_ID])
async def timer(ctx, название: str, days: int = 0, hours: int = 0, minutes: int = 0):
    if days == 0 and hours == 0 and minutes == 0:
        return await ctx.respond("❌ укажи время", ephemeral=True)

    channel_id = get_channel(ctx.guild.id, "simple")
    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    await ctx.defer(ephemeral=True)

    end = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        days=days,
        hours=hours,
        minutes=minutes
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

    await ctx.followup.send("✅ таймер создан", ephemeral=True)


@bot.slash_command(name="склад", guild_ids=[GUILD_ID])
async def sklad(ctx, гекс: str, регион: str, склад: str, пароль: str):
    channel_id = get_channel(ctx.guild.id, "sklad")

    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    await ctx.defer(ephemeral=True)

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

    await ctx.followup.send("✅ склад создан", ephemeral=True)


@bot.slash_command(name="мпф", guild_ids=[GUILD_ID])
async def mpf(ctx, что_поставил: str, ящиков: int, days: int = 0, hours: int = 0, minutes: int = 0):
    channel_id = get_channel(ctx.guild.id, "mpf")

    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    await ctx.defer(ephemeral=True)

    end = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        days=days,
        hours=hours,
        minutes=minutes
    )
    end_ts = int(end.timestamp())

    text = (
        f"👤 Кто поставил: {ctx.author.display_name}\n"
        f"📦 Что поставил: {что_поставил}\n"
        f"📦 Ящиков: {ящиков}\n"
        f"⌛ <t:{end_ts}:R>\n"
        f"Статус: ожидание"
    )

    msg = await ctx.send(text, view=MPFView(False))

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

    await ctx.followup.send("✅ MPF создан", ephemeral=True)

# ================= RUN =================

bot.run(os.environ.get("DISCORD_BOT_TOKEN"))
