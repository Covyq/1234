import os
import datetime
import traceback
import discord
from discord.ext import tasks
from discord.ui import View, Button
from peewee import *

# --- CONFIG ---
GUILD_ID = 1494712012314509372
ALLOWED_ROLE_IDS = [
    1493199914572972032,
    123456789012345678,
    987654321098765432,
    1477953756225081394,
    831242102179758100
]

bot = discord.Bot(intents=discord.Intents.all(), debug_guilds=[GUILD_ID])
db = SqliteDatabase("TimerDataBase.db")

# --- CACHE ---
CHANNEL_CACHE = {"sklad": {}, "simple": {}, "mpf": {}, "aktiv": {}}

# --- DATABASE MODELS ---
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

class Activity(BaseModel):
    guild_id = BigIntegerField()
    channel_id = BigIntegerField()
    message_id = BigIntegerField()
    author = BigIntegerField()
    name = TextField()
    location_hex = TextField()
    location_region = TextField()
    people_needed = TextField()
    voice_channel_id = BigIntegerField()
    created_at = DateTimeField(default=datetime.datetime.utcnow)

db.connect(reuse_if_open=True)
db.create_tables([ChannelConfig, Timer, Activity])

# --- CHANNEL MANAGEMENT FUNCTIONS ---
def load_channels():
    global CHANNEL_CACHE
    CHANNEL_CACHE = {"sklad": {}, "simple": {}, "mpf": {}, "aktiv": {}}
    for row in ChannelConfig.select():
        CHANNEL_CACHE.setdefault(row.channel_type, {})[row.guild_id] = row.channel_id

def set_channel(guild_id, channel_id, channel_type):
    row = ChannelConfig.get_or_none(
        (ChannelConfig.guild_id == guild_id) & (ChannelConfig.channel_type == channel_type)
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

def clean_channels():
    for row in ChannelConfig.select():
        guild = bot.get_guild(row.guild_id)
        if not guild or guild.get_channel_or_thread(row.channel_id) is None:
            row.delete_instance()

# --- USER ACCESS CONTROL ---
def has_access(member):
    return member.guild_permissions.administrator or any(
        r.id in ALLOWED_ROLE_IDS for r in member.roles
    )

# --- BUTTON VIEWS ---
class SkladView(View):
    def __init__(self):
        super().__init__(timeout=None)
        btn_update = Button(label="Обновить склад", style=discord.ButtonStyle.green, custom_id="sklad_update")
        btn_delete = Button(label="Удалить", style=discord.ButtonStyle.red, custom_id="sklad_delete")
        btn_update.callback = self.update
        btn_delete.callback = self.delete
        self.add_item(btn_update)
        self.add_item(btn_delete)

    async def update(self, interaction):
        await interaction.response.defer()
        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row:
            return await interaction.followup.send("❌ Не найдено", ephemeral=True)
        now = datetime.datetime.now(datetime.timezone.utc)
        new_end = int((now + datetime.timedelta(hours=48)).timestamp())
        row.time_end = new_end
        row.save()
        nickname = interaction.user.display_name
        updated_text = f"{row.text}\n\n⏰ До окончания: <t:{new_end}:R>\n\n🔄 Обновил склад - {nickname}"
        await interaction.message.edit(content=updated_text, view=self)

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
        btn = Button(label="Удалить таймер", style=discord.ButtonStyle.red, custom_id="timer_delete")
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
        delete_btn = Button(label="Удалить таймер", style=discord.ButtonStyle.red, custom_id="mpf_delete")
        take_btn = Button(label="Забрал заказ", style=discord.ButtonStyle.green, custom_id="mpf_take", disabled=not show_take)
        
        async def take_callback(interaction):
            await interaction.response.defer()
            row = Timer.get_or_none(Timer.message_id == interaction.message.id)
            if not row or row.taken_by:
                return await interaction.followup.send("❌ Уже забрали", ephemeral=True)
            row.taken_by = interaction.user.id
            row.save()
            nickname = interaction.user.display_name
            await interaction.message.edit(content=interaction.message.content + f"\n\n📦 Забрал: {nickname}", view=self)
            await interaction.followup.send("✅ Забрал", ephemeral=True)
        
        async def delete_callback(interaction):
            await interaction.response.defer()
            row = Timer.get_or_none(Timer.message_id == interaction.message.id)
            if not row or interaction.user.id != row.author:
                return await interaction.followup.send("❌ Только автор", ephemeral=True)
            row.delete_instance()
            await interaction.message.delete()
        
        take_btn.callback = take_callback
        delete_btn.callback = delete_callback

        self.add_item(delete_btn)
        self.add_item(take_btn)


class ActivityView(View):
    def __init__(self, author_id):
        super().__init__(timeout=None)
        
        async def delete_callback(interaction):
            has_rights_to_delete = (
                interaction.user.id == author_id or 
                has_access(interaction.user) or 
                interaction.user.guild_permissions.administrator
            )
            
            if not has_rights_to_delete:
                return await interaction.response.send_message(
                    "❌ У вас нет прав на удаление этой активности.",
                    ephemeral=True
                )
            
            activity_row = Activity.get_or_none(Activity.message_id == interaction.message.id)
            if activity_row:
                activity_row.delete_instance()
            
            try:
                await interaction.response.defer()
                await interaction.message.delete()
                await interaction.followup.send("✅ Активность удалена.", ephemeral=True)
            except discord.NotFound:
                pass

        delete_btn = Button(label="Удалить активность", style=discord.ButtonStyle.red, custom_id="activity_delete")
        delete_btn.callback = delete_callback
        
        self.add_item(delete_btn)


# --- BACKGROUND TASK FOR TIMER CHECKING ---
@tasks.loop(seconds=30)
async def loop():
    now_ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    
    # Check expired timers
    expired_timers = Timer.select().where(Timer.time_end < now_ts)
    
    for t in expired_timers:
        try:
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
            except discord.NotFound:
                t.delete_instance()
                continue

            member = guild.get_member(t.author)
            nickname = member.display_name if member else "пользователь"
            
            if t.kind == "mpf":
                item_text = t.text.split("📦 Что поставил: ")[1].splitlines()[0]
                
                new_content = (
                    f"👤 Кто поставил: {nickname}\n"
                    f"📦 Что поставил: {item_text}\n"
                    f"📦 Ящиков: {t.boxes}\n"
                    f"Статус: ✅"
                )
                
                await msg.edit(content=new_content, view=MPFView(show_take=True))
                
                # Set time far into future to avoid deletion next cycle
                t.time_end += (3600 * 24 * 365 * 10) 
                t.save()
                
            elif t.kind == "timer":
                new_content = (
                    f"👤 {member.mention if member else 'пользователь'}\n"
                    f"📌 {t.text}\n"
                    f"✅ Статус: выполнено"
                )
                
                await msg.edit(content=new_content, view=TimerView())
                
                t.time_end += (3600 * 24 * 365 * 10) 
                t.save()
                
            elif t.kind == "sklad":
                await msg.edit(
                    content=f"✅ Склад завершён {nickname}\n⏰ <t:{now_ts}:R>",
                    view=None # Remove buttons after completion
                )
                
                t.delete_instance() # Completely remove record

        except Exception as e:
            print(f"[ERROR] in loop for Timer ID {t.id}: {e}")
            print(traceback.format_exc())


# --- ON_READY EVENT ---
@bot.event
async def on_ready():
    print(f"Bot online as {bot.user}")
    clean_channels() # Clean up non-existing channels on startup
    load_channels() # Load cached channels from DB

    # Register views with the bot
    bot.add_view(SkladView())
    bot.add_view(TimerView())
    
    # MPFView needs to be registered without showing the "Take" button initially
    bot.add_view(MPFView(show_take=False))
    
    # ActivityView will be dynamically added when creating activities
    
    if not loop.is_running():
        loop.start() # Start background task for checking timers


# --- SLASH COMMANDS ---
@bot.slash_command(name="setskladchannel", guild_ids=[GUILD_ID])
async def setskladchannel(ctx, channel: discord.TextChannel):
    """
    Назначает канал для складов.
    Доступно только администраторам и ролям из списка разрешенных.
    """
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)
    
    set_channel(ctx.guild.id, channel.id, "sklad")
    await ctx.respond("✅ Канал склада назначен", ephemeral=True)


@bot.slash_command(name="setsimpletimer", guild_ids=[GUILD_ID])
async def setsimpletimer(ctx, channel: discord.TextChannel | None, thread_id: str | None):
    """
    Назначает канал или тред для простых таймеров.
    Доступно только администраторам и ролям из списка разрешенных.
    """
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)
    
    target_id = None
    if channel:
        target_id = channel.id
    elif thread_id:
        try:
            target_id = int(thread_id)
        except ValueError:
            return await ctx.respond("❌ Неверный ID треда", ephemeral=True)
    else:
        return await ctx.respond("❌ Укажите канал или thread_id", ephemeral=True)
    
    set_channel(ctx.guild.id, target_id, "simple")
    await ctx.respond(f"✅ Простые таймеры настроены в: {target_id}", ephemeral=True)


@bot.slash_command(name="setmpf", guild_ids=[GUILD_ID])
async def setmpf(ctx, channel: discord.TextChannel | None, thread_id: str | None):
    """
    Назначает канал или тред для MPF.
    Доступно только администраторам и ролям из списка разрешенных.
    """
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)
    
    target_id = None
    if channel:
        target_id = channel.id
    elif thread_id:
        try:
            target_id = int(thread_id)
        except ValueError:
            return await ctx.respond("❌ Неверный ID треда", ephemeral=True)
    else:
        return await ctx.respond("❌ Укажите канал или thread_id", ephemeral=True)
    
    set_channel(ctx.guild.id, target_id, "mpf")
    await ctx.respond(f"✅ MPF настроен в: {target_id}", ephemeral=True)


@bot.slash_command(name="setaktivchat", guild_ids=[GUILD_ID])
async def setaktivchat(ctx, channel: discord.TextChannel | None, thread_id: str | None):
    """
    Назначает канал или тред для создания активностей.
    Доступно только администраторам и ролям из списка разрешенных.
    """
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)
    
    target_id = None
    if channel:
        target_id = channel.id
    elif thread_id:
        try:
            target_id = int(thread_id)
        except ValueError:
            return await ctx.respond("❌ Неверный ID треда", ephemeral=True)
    else:
        return await ctx.respond("❌ Укажите канал или thread_id", ephemeral=True)
    
    set_channel(ctx.guild.id, target_id, "aktiv")
    await ctx.respond(f"✅ Канал для активностей назначен: {target_id}", ephemeral=True)


@bot.slash_command(name="таймер", guild_ids=[GUILD_ID])
async def timer(ctx, название: str, дни: int=0, часы: int=0, минуты: int=0):
    """
    Создает простой таймер.
    Доступно всем участникам сервера.
    """
    if дни == 0 and часы == 0 and минуты == 0:
        return await ctx.respond("❌ Укажите хотя бы одно значение времени (дни/часы/минуты)", ephemeral=True)
    
    simple_channel_id = get_channel(ctx.guild.id, "simple")
    
    # Ensure command is used in correct channel
    if not simple_channel_id or ctx.channel.id != simple_channel_id:
        return await ctx.respond("❌ Используйте команду в назначенном канале таймеров.", ephemeral=True)
    
    end_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        days=дни,
        hours=часы,
        minutes=минуты
    )
    
    end_timestamp = int(end_time.timestamp())
    
    # Send initial message with timer details
    msg = await ctx.send(
        f"👤 {ctx.author.mention}\n📌 {название}\n⏰ <t:{end_timestamp}:R>",
        view=TimerView()
    )
    
    # Save timer data to database
    Timer.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        text=название,
        time_end=end_timestamp,
        author=ctx.author.id,
        kind="timer"
    )
    
    await ctx.respond("✅ Таймер успешно создан.", ephemeral=True)


@bot.slash_command(name="склад", guild_ids=[GUILD_ID])
async def sklad(ctx, hex_: str, region: str, password: str):
    """
    Создает склад.
    Доступно всем участникам сервера.
    """
    sklad_channel_id = get_channel(ctx.guild.id, "sklad")
    
    # Ensure command is used in correct channel
    if sklad_channel_id and ctx.channel.id != sklad_channel_id:
        return await ctx.respond("❌ Используйте команду в назначенном канале складов.", ephemeral=True)
    
    end_timestamp = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=48)).timestamp())
    
    # Create formatted text for the warehouse
    text = (
        f"👤 {ctx.author.display_name}\n"
        f"**Гекс:** {hex_}\n"
        f"**Регион:** {region}\n"
        f"**Склад:** {password}"
    )
    
    # Send initial message with warehouse details
    msg = await ctx.send(
        f"{text}\n\n⏰ До окончания: <t:{end_timestamp}:R>",
        view=SkladView()
    )
    
    # Save warehouse data to database
    Timer.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        text=text,
        time_end=end_timestamp,
        author=ctx.author.id,
        kind="sklad"
    )
    
    await ctx.respond("✅ Склад успешно создан.", ephemeral=True)


@bot.slash_command(name="мпф", guild_ids=[GUILD_ID])
async def mpf(ctx, what_placed: str, boxes: int, days: int=0, hours: int=0, minutes: int=0):
    """
    Создает MPF (Multiplayer Fortress).
    Доступно всем участникам сервера.
    """
    mpf_channel_id = get_channel(ctx.guild.id, "mpf")
    
    # Ensure command is used in correct channel
    if not mpf_channel_id or ctx.channel.id != mpf_channel_id:
        return await ctx.respond("❌ Используйте команду в назначенном канале MPF.", ephemeral=True)
    
    end_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        days=days,
        hours=hours,
        minutes=minutes
    )
    
    end_timestamp = int(end_time.timestamp())
    
    # Create formatted text for the MPF
    text = (
        f"👤 Кто поставил: {ctx.author.display_name}\n"
        f"📦 Что поставил: {what_placed}\n"
        f"📦 Ящиков: {boxes}\n"
        f"⌛ <t:{end_timestamp}:R>\n"
        f"Статус: ожидание"
    )
    
    # Send initial message with MPF details
    msg = await ctx.send(text, view=MPFView(show_take=False))
    
    # Save MPF data to database
    Timer.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        text=text,
        time_end=end_timestamp,
        author=ctx.author.id,
        kind="mpf",
        boxes=boxes,
        taken_by=None
    )
    
    await ctx.respond("✅ MPF успешно создан.", ephemeral=True)


@bot.slash_command(name="активность", guild_ids=[GUILD_ID])
async def aktivnost(ctx, название: str, hex_: str, region: str, needed_people: str, voice_channel: discord.VoiceChannel):
    """
    Создает игровую активность.
    Доступно только администраторам и ролям из списка разрешенных.
    """
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)
    
    aktiv_channel_id = get_channel(ctx.guild.id, "aktiv")
    
    # Ensure command is used in correct channel
    if not aktiv_channel_id or ctx.channel.id != aktiv_channel_id:
        return await ctx.respond("❌ Используйте команду в назначенном канале активностей.", ephemeral=True)
    
    # Create an embedded message for better visual representation
    embed = discord.Embed(title="Новая игровая активность", color=0xFF5733)
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url)
    embed.add_field(name="Название:", value=название, inline=False)
    embed.add_field(name="Локация:", value=f"Гекс: `{hex_}` | Регион: `{region}`", inline=False)
    embed.add_field(name="Нужно людей:", value=needed_people, inline=False)
    embed.add_field(name="Голосовой канал:", value=voice_channel.mention, inline=False)
    embed.set_footer(text=f"Создано: {datetime.datetime.now().strftime('%H:%M %d.%m.%y')}")
    
    # Send initial message with activity details
    msg = await ctx.send(embed=embed, view=ActivityView(author_id=ctx.author.id))
    
    # Save activity data to database
    Activity.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        author=ctx.author.id,
        name=название,
        location_hex=hex_,
        location_region=region,
        people_needed=needed_people,
        voice_channel_id=voice_channel.id
    )
    
    await ctx.respond("✅ Активность создана.", ephemeral=True)


# --- START THE BOT ---
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
