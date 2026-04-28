import os
import asyncio
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

NOTIFY_TASKS = {}

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
        ChannelConfig.create(
            guild_id=guild_id,
            channel_id=channel_id,
            channel_type=channel_type
        )
    CHANNEL_CACHE[channel_type][guild_id] = channel_id

def get_channel(guild_id, channel_type):
    return CHANNEL_CACHE.get(channel_type, {}).get(guild_id)

# ================= PERMS =================

def has_access(member):
    return member.guild_permissions.administrator or any(r.id in ALLOWED_ROLE_IDS for r in member.roles)

def has_aktiv_access(member):
    return member.guild_permissions.administrator or any(r.id in AKTIV_ROLE_IDS for r in member.roles)

# ================= УВЕДОМЛЕНИЯ СКЛАДА =================

def cancel_notifications(message_id):
    tasks = NOTIFY_TASKS.pop(message_id, [])
    for task in tasks:
        task.cancel()

async def schedule_sklad_notifications(timer_row, channel):
    message_id = timer_row.message_id

    async def notify(delay, text):
        await asyncio.sleep(delay)
        if message_id not in NOTIFY_TASKS:
            return
        try:
            await channel.send(text)
        except:
            pass

    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    end = timer_row.time_end

    tasks = []

    def add(delay, text):
        task = bot.loop.create_task(notify(delay, text))
        tasks.append(task)

    sklad_name = timer_row.text.split("**Склад:**")[-1].split("\n")[0].strip()
    base_text = f"@склад\nСклад {sklad_name} скоро сгорит! Пожалуйста обновите его!"

    t3 = end - 10800
    if t3 > now:
        add(t3 - now, base_text)

    for i in range(2):
        t = end - 7200 + i * 1800
        if t > now:
            add(t - now, base_text + "!!!")

    for i in range(6):
        t = end - 3600 + i * 600
        if t > now:
            add(t - now, base_text + "!!!")

    NOTIFY_TASKS[message_id] = tasks

# ================= MPF TIMER =================

async def enable_mpf_button(message, view, delay):
    await asyncio.sleep(delay)

    for item in view.children:
        if item.custom_id == "mpf_claim":
            item.disabled = False

    try:
        content = message.content
        lines = content.split("\n")
        lines = [line for line in lines if not line.startswith("⏰")]
        lines.append("✅ Заказ готов")

        await message.edit(content="\n".join(lines), view=view)
    except:
        pass

# ================= VIEWS =================

class SkladView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Обновить склад", style=discord.ButtonStyle.green, custom_id="sklad_update")
    async def update(self, button, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row:
            return

        cancel_notifications(row.message_id)

        new_end = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=48)).timestamp())
        row.time_end = new_end
        row.save()

        nickname = interaction.user.display_name

        new_text = f"{row.text}\n⏰ <t:{new_end}:R>\n🔄 Обновил: {nickname}"

        await interaction.message.edit(content=new_text, view=self)

        notify_channel_id = get_channel(interaction.guild.id, "sklad_notify")
        if notify_channel_id:
            ch = interaction.guild.get_channel(notify_channel_id)
            if ch:
                await schedule_sklad_notifications(row, ch)

    @discord.ui.button(label="Удалить", style=discord.ButtonStyle.red, custom_id="sklad_delete")
    async def delete(self, button, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return

        cancel_notifications(row.message_id)
        row.delete_instance()
        await interaction.message.delete()

class TimerView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Удалить таймер", style=discord.ButtonStyle.red, custom_id="timer_delete")
    async def delete(self, button, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return

        row.delete_instance()
        await interaction.message.delete()

class MPFView(View):
    def __init__(self, message_id=0, end_time=0):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.end_time = end_time
        self.claimed = False

    @discord.ui.button(label="Забрал заказ", style=discord.ButtonStyle.green, custom_id="mpf_claim", disabled=True)
    async def claim(self, button, interaction):
        if self.claimed:
            return await interaction.response.send_message("❌ Уже забрали", ephemeral=True)

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row:
            return

        self.claimed = True
        button.disabled = True

        text = interaction.message.content + f"\n✅ Забрал заказ: {interaction.user.display_name}"
        await interaction.response.edit_message(content=text, view=self)

    @discord.ui.button(label="Удалить", style=discord.ButtonStyle.red, custom_id="mpf_delete")
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

    @discord.ui.button(label="Удалить активность", style=discord.ButtonStyle.danger, custom_id="aktiv_delete")
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

@bot.slash_command(name="setmpf", guild_ids=[GUILD_ID])
async def setmpf(ctx, channel: discord.TextChannel):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    set_channel(ctx.guild.id, channel.id, "mpf")
    await ctx.respond("✅ MPF канал установлен", ephemeral=True)

@bot.slash_command(name="setaktivchat", guild_ids=[GUILD_ID])
async def setaktivchat(ctx, channel: discord.TextChannel):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    set_channel(ctx.guild.id, channel.id, "aktiv")
    await ctx.respond("✅ Актив чат установлен", ephemeral=True)

# ===== АКТИВНОСТЬ =====

@bot.slash_command(name="активность", guild_ids=[GUILD_ID])
async def aktivnost(ctx, цель: str, гекс: str, регион: str, количество: int, voice: discord.VoiceChannel):
    if not has_aktiv_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    channel_id = get_channel(ctx.guild.id, "aktiv")
    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    embed = discord.Embed(color=discord.Color.blue())
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    embed.description = f"**{цель}**"
    embed.add_field(name="📍 Локация", value=f"{гекс}, {регион}", inline=False)
    embed.add_field(name="👥 Нужно людей", value=str(количество), inline=False)
    embed.add_field(name="", value=f"🔊 {voice.mention}", inline=False)

    await ctx.send(embed=embed, view=AktivView(ctx.author.id))
    await ctx.respond("✅ создано", ephemeral=True)

# ===== ТАЙМЕР =====

@bot.slash_command(name="таймер", guild_ids=[GUILD_ID])
async def timer(ctx, название: str, дни: int = 0, часы: int = 0, минуты: int = 0):
    await ctx.defer(ephemeral=True)

    channel_id = get_channel(ctx.guild.id, "simple")
    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.followup.send("❌ не тот канал", ephemeral=True)

    total = дни*86400 + часы*3600 + минуты*60
    if total <= 0:
        return await ctx.followup.send("❌ укажи время", ephemeral=True)

    end = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=total)
    ts = int(end.timestamp())

    msg = await ctx.channel.send(
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

    await ctx.followup.send("✅ таймер создан", ephemeral=True)

# ===== СКЛАД =====

@bot.slash_command(name="склад", guild_ids=[GUILD_ID])
async def sklad(ctx, гекс: str, регион: str, склад: str, пароль: str):
    await ctx.defer(ephemeral=True)

    channel_id = get_channel(ctx.guild.id, "sklad")
    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.followup.send("❌ не тот канал", ephemeral=True)

    end_ts = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=48)).timestamp())

    text = (
        f"👤 {ctx.author.display_name}\n"
        f"**Гекс:** {гекс}\n"
        f"**Регион:** {регион}\n"
        f"**Склад:** {склад}\n"
        f"**Пароль:** {пароль}"
    )

    msg = await ctx.channel.send(f"{text}\n⏰ <t:{end_ts}:R>", view=SkladView())

    timer_row = Timer.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        text=text,
        time_end=end_ts,
        author=ctx.author.id
    )

    notify_channel_id = get_channel(ctx.guild.id, "sklad_notify")
    if notify_channel_id:
        ch = ctx.guild.get_channel(notify_channel_id)
        if ch:
            await schedule_sklad_notifications(timer_row, ch)

    await ctx.followup.send("✅ склад создан", ephemeral=True)

# ===== MPF (ОБНОВЛЕННЫЙ) =====

@bot.slash_command(name="мпф", guild_ids=[GUILD_ID])
async def mpf(
    ctx,
    что: str,
    ящиков: int,
    дни: int = 0,
    часы: int = 0,
    минуты: int = 0,
    куда: str = "channel",
    thread_id: str = None
):
    await ctx.defer(ephemeral=True)

    channel_id = get_channel(ctx.guild.id, "mpf")
    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.followup.send("❌ не тот канал", ephemeral=True)

    target_channel = ctx.channel

    if куда == "thread":
        if not thread_id:
            return await ctx.followup.send("❌ укажи ID ветки", ephemeral=True)

        try:
            thread = ctx.guild.get_thread(int(thread_id))
            if not thread:
                thread = await ctx.guild.fetch_channel(int(thread_id))
            target_channel = thread
        except:
            return await ctx.followup.send("❌ не удалось найти ветку", ephemeral=True)

    total = дни*86400 + часы*3600 + минуты*60

    end_ts = 0
    time_text = ""

    if total > 0:
        end = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=total)
        end_ts = int(end.timestamp())
        time_text = f"\n⏰ <t:{end_ts}:R>"

    text = f"👤 {ctx.author.display_name}\n📦 {что}\n📦 Ящиков: {ящиков}{time_text}"

    view = MPFView(0, end_ts)
    msg = await target_channel.send(text, view=view)

    view.message_id = msg.id

    Timer.create(
        guild_id=ctx.guild.id,
        channel_id=target_channel.id,
        message_id=msg.id,
        text=text,
        time_end=end_ts,
        author=ctx.author.id
    )

    if total > 0:
        bot.loop.create_task(enable_mpf_button(msg, view, total))
    else:
        for item in view.children:
            if item.custom_id == "mpf_claim":
                item.disabled = False
        await msg.edit(view=view)

    await ctx.followup.send("✅ MPF создан", ephemeral=True)

# ================= START =================

@bot.event
async def on_ready():
    print(f"Bot online {bot.user}")
    load_channels()

    bot.add_view(SkladView())
    bot.add_view(TimerView())
    bot.add_view(MPFView())
    bot.add_view(AktivView(0))

bot.run(os.environ.get("DISCORD_BOT_TOKEN"))
