import os
import datetime
import traceback
import discord
from discord.ext import tasks
from discord.ui import View, button
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
    message_id = BigIntegerField(index=True)
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


# ================= SAFE =================

async def get_guild_safe(guild_id):
    return bot.get_guild(guild_id) or await bot.fetch_guild(guild_id)


async def get_channel_safe(guild, channel_id):
    return guild.get_channel_or_thread(channel_id) or await bot.fetch_channel(channel_id)


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
    cid = CHANNEL_CACHE.get(channel_type, {}).get(guild_id)
    if not cid:
        load_channels()
        cid = CHANNEL_CACHE.get(channel_type, {}).get(guild_id)
    return cid


# ================= PERMS =================

def has_access(member):
    return member.guild_permissions.administrator or any(
        r.id in ALLOWED_ROLE_IDS for r in member.roles
    )


# ================= EVENTS =================

@bot.event
async def on_raw_message_delete(payload):
    Timer.delete().where(Timer.message_id == payload.message_id).execute()


# ================= NOTIFICATIONS =================

async def send_sklad_notification(t):
    try:
        guild = await get_guild_safe(t.guild_id)
        notify_channel_id = get_channel(t.guild_id, "sklad_notify")
        if not notify_channel_id:
            return

        channel = await get_channel_safe(guild, notify_channel_id)

        try:
            sklad_name = t.text.split("**Склад:** ")[1].splitlines()[0]
        except:
            sklad_name = "неизвестно"

        msg = await channel.send(f"⚠️ Склад **{sklad_name}** скоро сгорит!")

        ids = t.notify_messages.split(",") if t.notify_messages else []
        ids.append(str(msg.id))

        t.notify_messages = ",".join(ids)
        t.save()

    except Exception as e:
        print(f"[NOTIFY ERROR] {e}")


async def delete_notifications(t, guild):
    try:
        if not t.notify_messages:
            return

        notify_channel_id = get_channel(t.guild_id, "sklad_notify")
        if not notify_channel_id:
            return

        channel = await get_channel_safe(guild, notify_channel_id)

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

    except Exception as e:
        print(f"[DELETE NOTIFY ERROR] {e}")


# ================= VIEWS =================

class SkladView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @button(label="Обновить склад", style=discord.ButtonStyle.green, custom_id="sklad_update")
    async def update(self, btn, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row:
            return

        await delete_notifications(row, interaction.guild)

        now = datetime.datetime.now(datetime.timezone.utc)
        new_end = int((now + datetime.timedelta(hours=48)).timestamp())

        row.time_end = new_end
        row.save()

        await interaction.message.edit(
            content=f"{row.text}\n⏰ <t:{new_end}:R>",
            view=self
        )

    @button(label="Удалить", style=discord.ButtonStyle.red, custom_id="sklad_delete")
    async def delete(self, btn, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return

        await delete_notifications(row, interaction.guild)
        row.delete_instance()
        await interaction.message.delete()


class TimerView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @button(label="Удалить таймер", style=discord.ButtonStyle.red, custom_id="timer_delete")
    async def delete(self, btn, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return

        row.delete_instance()
        await interaction.message.delete()


class MPFView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @button(label="Удалить таймер", style=discord.ButtonStyle.red, custom_id="mpf_delete")
    async def delete(self, btn, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return

        row.delete_instance()
        await interaction.message.delete()

    @button(label="Забрал заказ", style=discord.ButtonStyle.green, custom_id="mpf_take")
    async def take(self, btn, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or row.taken_by:
            return

        row.taken_by = interaction.user.id
        row.save()

        await interaction.message.edit(
            content=interaction.message.content + f"\n📦 Забрал: {interaction.user.display_name}",
            view=self
        )


# ================= LOGIC =================

async def process_expired_timer(t):
    try:
        guild = await get_guild_safe(t.guild_id)
        channel = await get_channel_safe(guild, t.channel_id)
        msg = await channel.fetch_message(t.message_id)
    except Exception as e:
        print(f"[EXPIRE ERROR] {e}")
        return

    if t.kind == "sklad":
        await delete_notifications(t, guild)
        await msg.edit(content=f"{t.text}\n🔥 Склад сгорел!", view=None)
        t.delete_instance()

    elif t.kind == "timer":
        await msg.edit(content=f"{t.text}\n✅ выполнено", view=TimerView())

    elif t.kind == "mpf":
        await msg.edit(content=f"{t.text}\n✅ готово", view=MPFView())


# ================= RESTORE =================

async def restore_messages():
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    for t in Timer.select():
        try:
            guild = await get_guild_safe(t.guild_id)
            channel = await get_channel_safe(guild, t.channel_id)
            msg = await channel.fetch_message(t.message_id)

            if t.time_end < now:
                await process_expired_timer(t)
                continue

            if t.kind == "sklad":
                await msg.edit(view=SkladView())
            elif t.kind == "timer":
                await msg.edit(view=TimerView())
            elif t.kind == "mpf":
                await msg.edit(view=MPFView())

        except Exception as e:
            print(f"[RESTORE ERROR] {e}")
            continue


# ================= LOOP =================

@tasks.loop(seconds=30)
async def loop():
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    for t in Timer.select():
        try:
            if t.kind == "sklad":
                remaining = t.time_end - now

                if 7200 < remaining <= 10800 and not t.notified_3h:
                    await send_sklad_notification(t)
                    t.notified_3h = True
                    t.last_notify_time = now
                    t.save()

                elif 3600 < remaining <= 7200:
                    if t.notified_2h < 2 and (not t.last_notify_time or now - t.last_notify_time >= 1800):
                        await send_sklad_notification(t)
                        t.notified_2h += 1
                        t.last_notify_time = now
                        t.save()

                elif remaining <= 3600:
                    if t.notified_1h < 6 and (not t.last_notify_time or now - t.last_notify_time >= 600):
                        await send_sklad_notification(t)
                        t.notified_1h += 1
                        t.last_notify_time = now
                        t.save()

            if t.time_end < now:
                await process_expired_timer(t)

        except Exception as e:
            print(f"[LOOP ERROR] {e}")


# ================= READY =================

@bot.event
async def on_ready():
    print(f"Bot online {bot.user}")

    load_channels()

    bot.add_view(SkladView())
    bot.add_view(TimerView())
    bot.add_view(MPFView())

    await restore_messages()

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
async def timer(ctx, название: str, minutes: int):
    end = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)
    ts = int(end.timestamp())

    msg = await ctx.send(f"{название}\n⏰ <t:{ts}:R>", view=TimerView())

    Timer.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        text=название,
        time_end=ts,
        author=ctx.author.id,
        kind="timer"
    )


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

    msg = await ctx.send(f"{text}\n⏰ <t:{end_ts}:R>", view=SkladView())

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
    ts = int(end.timestamp())

    text = (
        f"👤 {ctx.author.display_name}\n"
        f"📦 {что_поставил}\n"
        f"📦 Ящиков: {ящиков}\n"
        f"⌛ <t:{ts}:R>"
    )

    msg = await ctx.send(text, view=MPFView())

    Timer.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        text=text,
        time_end=ts,
        author=ctx.author.id,
        kind="mpf",
        boxes=ящиков
    )


# RUN
bot.run(os.environ.get("DISCORD_BOT_TOKEN"))
