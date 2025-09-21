import discord
from discord.ext import commands, tasks
import os
import random
import asyncio
import json
from datetime import datetime, timedelta
import re
import time
from keep_alive import keep_alive

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Global variables for combined functionality
tournaments = {}  # {guild_id: Tournament}
sp_data = {}  # {guild_id: {user_id: sp_amount}}
role_permissions = {}  # {guild_id: {'htr': [role_ids], 'adr': [role_ids], 'tlr': [role_ids]}}
teams = {}  # {guild_id: {team_id: [player1, player2]}}
team_invitations = {}  # {guild_id: {user_id: [inviter_id1, inviter_id2, ...]}}
player_teams = {}  # {guild_id: {user_id: team_id}}
log_channels = {}  # {guild_id: channel_id}
bracket_roles = {}  # {guild_id: {user_id: [emoji1, emoji2, ...]}}
logs_channels = {}  # {guild_id: channel_id} for !logs command
logs_messages = {}  # {guild_id: message_id} to track auto-updating messages
active_games = {}  # {guild_id: {'number': int, 'range': [min, max], 'channel_id': int}}
host_registrations = {'active': False, 'hosters': [], 'max_hosters': 10}

# Tournament class
class Tournament:
    def __init__(self):
        self.players = []
        self.max_players = 0
        self.active = False
        self.channel = None
        self.target_channel = None
        self.message = None
        self.rounds = []
        self.results = []
        self.eliminated = []
        self.fake_count = 1
        self.map = ""
        self.abilities = ""
        self.prize = ""
        self.title = ""
        self.mode = "1v1"

# Fake player class for tournaments
class FakePlayer:
    def __init__(self, name, user_id):
        self.display_name = name
        self.name = name
        self.nick = name
        self.id = user_id
        self.mention = f"@{user_id}"

    def __str__(self):
        return self.mention

def get_tournament(guild_id):
    """Get tournament for specific guild"""
    if guild_id not in tournaments:
        tournaments[guild_id] = Tournament()
    return tournaments[guild_id]

# JSON Database functions
def init_db():
    """Initialize JSON database files"""
    db_files = {
        'warnings.json': [],
        'user_levels.json': {},
        'guild_config.json': {},
        'level_roles.json': {},
        'automod_warnings.json': {},
        'user_accounts.json': {},
        'tickets.json': [],
        'user_data.json': {}
    }
    
    for filename, default_data in db_files.items():
        if not os.path.exists(filename):
            with open(filename, 'w') as f:
                json.dump(default_data, f)

def load_json(filename):
    """Load data from JSON file"""
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {} if filename != 'warnings.json' and filename != 'tickets.json' else []

def save_json(filename, data):
    """Save data to JSON file"""
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)

# Load and save data functions for SP system
def load_data():
    global sp_data, role_permissions, log_channels, bracket_roles, logs_channels
    try:
        with open('user_data.json', 'r') as f:
            data = json.load(f)
            sp_data = data.get('sp_data', {})
            role_permissions = data.get('role_permissions', {})
            log_channels = data.get('log_channels', {})
            bracket_roles = data.get('bracket_roles', {})
            logs_channels = data.get('logs_channels', {})
            # Teams data is not loaded since it contains Discord objects
            teams.clear()
            team_invitations.clear()
            player_teams.clear()
    except FileNotFoundError:
        pass

def save_data():
    data = {
        'sp_data': sp_data,
        'role_permissions': role_permissions,
        'log_channels': log_channels,
        'bracket_roles': bracket_roles,
        'logs_channels': logs_channels
    }
    with open('user_data.json', 'w') as f:
        json.dump(data, f)

def add_sp(guild_id, user_id, sp):
    """Add seasonal points to a user"""
    guild_str = str(guild_id)
    user_str = str(user_id)

    if guild_str not in sp_data:
        sp_data[guild_str] = {}

    if user_str not in sp_data[guild_str]:
        sp_data[guild_str][user_str] = 0

    sp_data[guild_str][user_str] += sp
    save_data()
    # Update logs message when SP changes
    asyncio.create_task(update_logs_message(guild_id))

def get_sp(guild_id, user_id):
    """Get seasonal points for a user"""
    guild_str = str(guild_id)
    user_str = str(user_id)
    return sp_data.get(guild_str, {}).get(user_str, 0)

# Helper functions
def parse_time(time_str):
    """Parse time string like '1h', '30m', '2d' into timedelta"""
    if not time_str:
        return None
    
    match = re.match(r'(\d+)([mhdmo]+)', time_str.lower())
    if not match:
        return None
    
    amount, unit = match.groups()
    amount = int(amount)
    
    if unit == 'm':
        return timedelta(minutes=amount)
    elif unit == 'h':
        return timedelta(hours=amount)
    elif unit == 'd':
        return timedelta(days=amount)
    elif unit == 'mo':
        return timedelta(days=amount * 30)
    
    return None

async def is_staff(ctx):
    """Check if user is staff"""
    if ctx.author.guild_permissions.manage_messages:
        return True
    
    guild_config = load_json('guild_config.json')
    config = guild_config.get(str(ctx.guild.id), {})
    staff_roles = config.get('staff_roles', '')
    
    if staff_roles:
        staff_role_ids = staff_roles.split(',')
        user_role_ids = [str(role.id) for role in ctx.author.roles]
        return any(role_id in staff_role_ids for role_id in user_role_ids)
    
    return False

def has_permission(user, guild_id, permission_type):
    """Check if user has specific permission type"""
    guild_str = str(guild_id)
    if guild_str not in role_permissions:
        return False

    # ADR has all permissions
    if 'adr' in role_permissions[guild_str]:
        user_role_ids = [role.id for role in user.roles]
        adr_role_ids = role_permissions[guild_str]['adr']
        if any(role_id in adr_role_ids for role_id in user_role_ids):
            return True

    if permission_type not in role_permissions[guild_str]:
        return False

    user_role_ids = [role.id for role in user.roles]
    allowed_role_ids = role_permissions[guild_str][permission_type]

    return any(role_id in allowed_role_ids for role_id in user_role_ids)

def get_player_display_name(player, guild_id=None):
    """Get player display name"""
    if isinstance(player, FakePlayer):
        return player.display_name

    if hasattr(player, 'display_name'):
        return player.display_name
    elif hasattr(player, 'name'):
        return player.name
    else:
        return str(player)

def get_team_id(guild_id, user_id):
    """Get team ID for a user"""
    guild_str = str(guild_id)
    user_str = str(user_id)
    return player_teams.get(guild_str, {}).get(user_str)

def get_team_members(guild_id, team_id):
    """Get all members of a team"""
    guild_str = str(guild_id)
    return teams.get(guild_str, {}).get(team_id, [])

def get_teammate(guild_id, user_id):
    """Get the teammate of a user"""
    team_id = get_team_id(guild_id, user_id)
    if not team_id:
        return None
    team_members = get_team_members(guild_id, team_id)
    for member in team_members:
        if member.id != user_id:
            return member
    return None

def create_team(guild_id, player1, player2):
    """Create a new team with two players"""
    guild_str = str(guild_id)

    if guild_str not in teams:
        teams[guild_str] = {}
        player_teams[guild_str] = {}

    # Generate unique team ID
    team_id = f"team_{len(teams[guild_str]) + 1}_{guild_id}"

    teams[guild_str][team_id] = [player1, player2]
    player_teams[guild_str][str(player1.id)] = team_id
    player_teams[guild_str][str(player2.id)] = team_id

    return team_id

def remove_team(guild_id, team_id):
    """Remove a team and its members"""
    guild_str = str(guild_id)

    if guild_str in teams and team_id in teams[guild_str]:
        # Remove players from player_teams
        for player in teams[guild_str][team_id]:
            if str(player.id) in player_teams[guild_str]:
                del player_teams[guild_str][str(player.id)]

        # Remove team
        del teams[guild_str][team_id]

def get_team_display_name(guild_id, team_members):
    """Get display name for a team"""
    if len(team_members) == 2:
        name1 = get_player_display_name(team_members[0], guild_id)
        name2 = get_player_display_name(team_members[1], guild_id)
        return f"{name1} & {name2}"
    return "Unknown Team"

async def log_command(guild_id, user, command, details=""):
    """Log tournament commands to designated channel"""
    guild_str = str(guild_id)
    if guild_str not in log_channels:
        return

    try:
        channel = bot.get_channel(log_channels[guild_str])
        if not channel:
            return

        embed = discord.Embed(
            title="📋 Tournament Command Used",
            color=0x3498db,
            timestamp=datetime.now()
        )

        embed.add_field(name="User", value=user.display_name, inline=True)
        embed.add_field(name="Command", value=command, inline=True)
        if details:
            embed.add_field(name="Details", value=details, inline=False)

        await channel.send(embed=embed)
    except Exception as e:
        print(f"Error logging command: {e}")

# Automod functions
BAD_WORDS = ['badword1', 'badword2', 'spam', 'test_bad']

async def check_spam(message):
    """Check if message is spam (5 same consecutive messages in 5 seconds)"""
    if not message.guild:
        return False
    
    channel = message.channel
    count = 0
    now = datetime.now()
    last_content = None
    
    async for msg in channel.history(limit=6):
        if msg.author == message.author:
            msg_time = msg.created_at.replace(tzinfo=None)
            time_diff = (now - msg_time).total_seconds()
            
            if time_diff <= 5:
                if last_content is None:
                    last_content = msg.content
                    count = 1
                elif msg.content == last_content:
                    count += 1
                else:
                    break
            else:
                break
        else:
            break
    
    return count >= 5

async def check_emoji_spam(message):
    """Check if user sends 5 consecutive emoji messages in 5 seconds"""
    if not message.guild:
        return False
    
    channel = message.channel
    count = 0
    now = datetime.now()
    emoji_pattern = r'<:[^:]+:\d+>|[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]'
    
    async for msg in channel.history(limit=6):
        if msg.author == message.author:
            msg_time = msg.created_at.replace(tzinfo=None)
            time_diff = (now - msg_time).total_seconds()
            
            if time_diff <= 5:
                emojis = re.findall(emoji_pattern, msg.content)
                if len(emojis) > 5:  # Message has more than 5 emojis
                    count += 1
                else:
                    break
            else:
                break
        else:
            break
    
    return count >= 5

async def check_bad_words(content):
    """Check if message contains 3 or more bad words"""
    content_lower = content.lower()
    bad_word_count = 0
    
    for bad_word in BAD_WORDS:
        words = content_lower.split()
        for word in words:
            if word.startswith(bad_word) or word.endswith(bad_word) or word == bad_word:
                bad_word_count += 1
                break
    
    return bad_word_count >= 3

async def check_links(content):
    """Check if message contains links"""
    url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    return bool(re.search(url_pattern, content))

# LOGS AND BRACKET ROLE INTEGRATION

async def update_logs_message(guild_id):
    """Update the logs message when data changes"""
    guild_str = str(guild_id)
    
    if guild_str not in logs_channels or guild_str not in logs_messages:
        return
    
    try:
        channel = bot.get_channel(logs_channels[guild_str])
        if not channel or not hasattr(channel, 'fetch_message'):
            return
        
        message = await channel.fetch_message(logs_messages[guild_str])
        if not message:
            return
        
        # Generate updated embed
        embeds = await generate_logs_embeds(guild_id)
        
        if embeds:
            # Update the first message
            await message.edit(embed=embeds[0])
            
            # If there are additional embeds, send them as new messages
            if len(embeds) > 1:
                for embed in embeds[1:]:
                    await channel.send(embed=embed)
    except:
        pass

async def generate_logs_embeds(guild_id):
    """Generate embeds for the logs command - shows only players with bracket roles, SP, or tournament participation"""
    guild = bot.get_guild(guild_id)
    if not guild:
        return []
    
    guild_str = str(guild_id)
    embeds = []
    current_embed = discord.Embed(
        title="📊 Server Activity Logs - Players with Bracket Roles & Tournament Data",
        color=0x00ff00,
        timestamp=datetime.now()
    )
    
    member_count = 0
    max_fields_per_embed = 25
    field_count = 0
    
    # Get tournament data
    tournament = get_tournament(guild_id)
    tournament_players = set()
    if tournament and tournament.players:
        for player in tournament.players:
            if hasattr(player, 'id') and not isinstance(player, FakePlayer):
                tournament_players.add(player.id)
    
    for member in guild.members:
        if member.bot:
            continue
            
        user_str = str(member.id)
        
        # Get linked account
        user_accounts = load_json('user_accounts.json')
        account_key = f"{guild_id}_{member.id}"
        account_data = user_accounts.get(account_key, {})
        linked_account = account_data.get('ign', 'Not Linked') if isinstance(account_data, dict) else 'Not Linked'
        
        # Get seasonal points
        sp_amount = get_sp(guild_id, member.id)
        
        # Get bracket roles (emojis)
        bracket_emojis = ''.join(bracket_roles.get(guild_str, {}).get(user_str, []))
        
        # Check tournament participation
        in_tournament = member.id in tournament_players
        
        # Only show members who have at least one of: bracket roles, SP > 0, tournament participation, or linked account
        if bracket_emojis or sp_amount > 0 or in_tournament or linked_account != 'Not Linked':
            field_value = f"• **Linked Account:** {member.mention} - {linked_account}\n"
            field_value += f"• **Seasonal Points:** {member.mention} - {sp_amount} SP\n"
            field_value += f"• **Bracket Roles:** {member.mention} - {bracket_emojis if bracket_emojis else 'None'}\n"
            field_value += f"• **Tournament Status:** {member.mention} - {'Registered' if in_tournament else 'Not Registered'}"
            
            current_embed.add_field(
                name=f"👤 {member.display_name}",
                value=field_value,
                inline=False
            )
            
            member_count += 1
            field_count += 1
            
            # Check if we need a new embed
            if field_count >= max_fields_per_embed:
                embeds.append(current_embed)
                current_embed = discord.Embed(
                    title="📊 Server Activity Logs - Players with Bracket Roles & Tournament Data (Continued)",
                    color=0x00ff00,
                    timestamp=datetime.now()
                )
                field_count = 0
    
    if field_count > 0 or member_count == 0:
        if member_count == 0:
            current_embed.add_field(
                name="No Active Members",
                value="No members with bracket roles, seasonal points, tournament participation, or linked accounts found.",
                inline=False
            )
        embeds.append(current_embed)
    
    return embeds

@bot.command()
async def logs(ctx, channel: discord.TextChannel):
    """Display server activity logs with linked accounts, SP, bracket roles, and tournament participation"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    guild_str = str(ctx.guild.id)
    logs_channels[guild_str] = channel.id
    save_data()
    
    embeds = await generate_logs_embeds(ctx.guild.id)
    
    if embeds:
        # Send the first embed and store its message ID for updates
        message = await channel.send(embed=embeds[0])
        logs_messages[guild_str] = message.id
        
        # Send additional embeds if needed
        for embed in embeds[1:]:
            await channel.send(embed=embed)
        
        await ctx.send(f"✅ Logs have been posted in {channel.mention} and will auto-update when data changes!")
    else:
        await ctx.send("❌ No data to display.")

@bot.command()
async def bracketrole(ctx, member: discord.Member, *emojis):
    """Add bracket role emojis to a user"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    guild_str = str(ctx.guild.id)
    user_str = str(member.id)
    
    if guild_str not in bracket_roles:
        bracket_roles[guild_str] = {}
    
    bracket_roles[guild_str][user_str] = list(emojis)
    save_data()
    
    # Update logs message
    await update_logs_message(ctx.guild.id)
    
    emoji_display = ''.join(emojis) if emojis else 'None'
    await ctx.send(f"✅ Bracket roles updated for {member.mention}: {emoji_display}")

# Tournament Configuration Views and Modals
class TournamentConfigModal(discord.ui.Modal):
    def __init__(self, target_channel):
        super().__init__(title="Tournament Configuration")
        self.target_channel = target_channel

    title_field = discord.ui.TextInput(
        label="🏆 Tournament Title",
        placeholder="Enter tournament title...",
        default="",
        max_length=100
    )

    map_field = discord.ui.TextInput(
        label="🗺️ Map",
        placeholder="Enter map name...",
        default="",
        max_length=50
    )

    abilities_field = discord.ui.TextInput(
        label="💥 Abilities",
        placeholder="Enter abilities...",
        default="",
        max_length=100
    )

    mode_and_players_field = discord.ui.TextInput(
        label="🎮 Mode & Max Players",
        placeholder="1v1 8 or 2v2 4 (format: mode maxplayers)",
        default="",
        max_length=20
    )

    prize_field = discord.ui.TextInput(
        label="💶 Prize",
        placeholder="Enter prize...",
        default="",
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Validate target channel
            if not self.target_channel:
                await interaction.response.send_message("❌ Invalid target channel. Please try again.", ephemeral=True)
                return

            # Parse mode and max players
            mode_players_parts = self.mode_and_players_field.value.strip().split()
            if len(mode_players_parts) != 2:
                await interaction.response.send_message("❌ Format should be: mode maxplayers (e.g., '1v1 8')", ephemeral=True)
                return

            mode = mode_players_parts[0].lower()
            max_players = int(mode_players_parts[1])

            if mode not in ["1v1", "2v2"]:
                await interaction.response.send_message("❌ Mode must be '1v1' or '2v2'!", ephemeral=True)
                return

            if mode == "2v2" and max_players not in [2, 4, 8, 16]:
                await interaction.response.send_message("❌ For 2v2 mode, max players (teams) must be 2, 4, 8, or 16!", ephemeral=True)
                return
            elif mode == "1v1" and max_players not in [2, 4, 8, 16, 32]:
                await interaction.response.send_message("❌ For 1v1 mode, max players must be 2, 4, 8, 16 or 32!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("❌ Invalid format! Use: mode maxplayers (e.g., '1v1 8')", ephemeral=True)
            return
        except Exception as e:
            print(f"Error in tournament config modal: {e}")
            await interaction.response.send_message("❌ An error occurred. Please try again.", ephemeral=True)
            return

        # Get server-specific tournament and reset it
        tournament = get_tournament(interaction.guild.id)
        tournament.__init__()
        tournament.max_players = max_players
        tournament.mode = mode
        tournament.channel = self.target_channel
        tournament.target_channel = self.target_channel
        tournament.title = self.title_field.value
        tournament.map = self.map_field.value
        tournament.abilities = self.abilities_field.value
        tournament.prize = self.prize_field.value
        tournament.players = []
        tournament.eliminated = []
        tournament.active = False

        embed = discord.Embed(title=f"🏆 {tournament.title}", color=0x00ff00)
        embed.add_field(name="<:map:1409924163346370560> Map", value=tournament.map, inline=True)
        embed.add_field(name="<:abilities:1402690411759407185> Abilities", value=tournament.abilities, inline=True)
        embed.add_field(name="🎮 Mode", value=mode, inline=True)
        embed.add_field(name="<:LotsOfGems:1383151614940151908> Prize", value=tournament.prize, inline=True)
        embed.add_field(name="<:TrioIcon:1402690815771541685> Max Players", value=str(max_players), inline=True)

        # Enhanced Stumble Guys rules with updated emojis
        rules_text = (
            "🔹 **NO TEAMING** - Teams are only allowed in designated team modes\n"
            "🔸 **NO GRIEFING** - Don't intentionally sabotage other players\n"
            "🔹 **NO EXPLOITING** - Use of glitches or exploits will result in disqualification\n"
            "🔸 **FAIR PLAY** - Respect all players and play honorably\n"
            "🔹 **NO RAGE QUITTING** - Leaving mid-match counts as a forfeit\n"
            "🔸 **FOLLOW HOST** - Listen to tournament host instructions\n"
            "🔹 **NO TOXICITY** - Keep chat friendly and respectful\n"
            "🔸 **BE READY** - Join matches promptly when called\n"
            "🔹 **NO ALTS** - One account per player only"
        )

        embed.add_field(name="<:notr:1409923674387251280> **Stumble Guys Tournament Rules**", value=rules_text, inline=False)

        view = TournamentView()
        # Update the participant count button to show correct max players
        for item in view.children:
            if hasattr(item, 'custom_id') and item.custom_id == "participant_count":
                item.label = f"0/{max_players}"
                break

        # Send tournament message
        tournament.message = await self.target_channel.send(embed=embed, view=view)

        # Update logs when tournament is created
        await update_logs_message(interaction.guild.id)

        # Log tournament creation
        details = f"Mode: {mode}, Max players: {max_players}, Map: {tournament.map}, Prize: {tournament.prize}"
        await log_command(interaction.guild.id, interaction.user, "Tournament Created", details)

        # Respond with success
        await interaction.response.send_message("✅ Tournament created successfully!", ephemeral=True)

        print(f"✅ Tournament created: {max_players} max players, Map: {tournament.map}")

class TournamentConfigView(discord.ui.View):
    def __init__(self, target_channel=None):
        super().__init__(timeout=None)
        self.target_channel = target_channel

    @discord.ui.button(label="Set Tournament", style=discord.ButtonStyle.primary, custom_id="set_tournament_config")
    async def set_tournament(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Use the channel where the interaction happened if no target channel is set
            target_channel = self.target_channel or interaction.channel

            # Ensure we have a valid channel
            if not target_channel:
                return await interaction.response.send_message("❌ Unable to determine target channel. Please try again.", ephemeral=True)

            modal = TournamentConfigModal(target_channel)
            await interaction.response.send_modal(modal)
        except Exception as e:
            print(f"Error in set_tournament: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ An error occurred. Please try again.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ An error occurred. Please try again.", ephemeral=True)
            except Exception as follow_error:
                print(f"Failed to send error message: {follow_error}")

class TournamentView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    @discord.ui.button(label="Register", style=discord.ButtonStyle.green, custom_id="tournament_register")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            tournament = get_tournament(interaction.guild.id)

            # Check tournament state
            if tournament.max_players == 0:
                return await interaction.response.send_message("❌ No tournament has been created yet.", ephemeral=True)
            if tournament.active:
                return await interaction.response.send_message("⚠️ Tournament already started.", ephemeral=True)

            # For 2v2 mode, check if user is in a team
            if tournament.mode == "2v2":
                team_id = get_team_id(interaction.guild.id, interaction.user.id)
                if not team_id:
                    return await interaction.response.send_message("❌ You need to be in a team to register for 2v2 tournaments! Use `!invite @teammate` to create a team.", ephemeral=True)

                # Check if team is already registered
                team_members = get_team_members(interaction.guild.id, team_id)
                if any(member in tournament.players for member in team_members):
                    return await interaction.response.send_message("❌ Your team is already registered.", ephemeral=True)

                # Check if tournament is full (max_players represents number of teams in 2v2)
                current_teams = len(tournament.players) // 2
                if current_teams >= tournament.max_players:
                    return await interaction.response.send_message("❌ Tournament is full.", ephemeral=True)

                tournament.players.extend(team_members)
                team_name = get_team_display_name(interaction.guild.id, team_members)

                for item in self.children:
                    if hasattr(item, 'custom_id') and item.custom_id == "participant_count":
                        teams_registered = len(tournament.players) // 2
                        item.label = f"{teams_registered}/{tournament.max_players}"
                        break

                await interaction.response.edit_message(view=self)
                await interaction.followup.send(f"✅ Team {team_name} registered! ({len(tournament.players) // 2}/{tournament.max_players} teams)", ephemeral=True)

            else:  # 1v1 mode
                if interaction.user in tournament.players:
                    return await interaction.response.send_message("❌ You are already registered.", ephemeral=True)

                # Check if there's space
                if len(tournament.players) >= tournament.max_players:
                    return await interaction.response.send_message("❌ Tournament is full.", ephemeral=True)

                tournament.players.append(interaction.user)

                for item in self.children:
                    if hasattr(item, 'custom_id') and item.custom_id == "participant_count":
                        item.label = f"{len(tournament.players)}/{tournament.max_players}"
                        break

                await interaction.response.edit_message(view=self)
                await interaction.followup.send(f"✅ {interaction.user.display_name} registered! ({len(tournament.players)}/{tournament.max_players})", ephemeral=True)

            # Update logs when someone registers
            await update_logs_message(interaction.guild.id)

        except Exception as e:
            print(f"Error in register_button: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ An error occurred. Please try again.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ An error occurred. Please try again.", ephemeral=True)
            except Exception as follow_error:
                print(f"Failed to send error message: {follow_error}")

    @discord.ui.button(label="Unregister", style=discord.ButtonStyle.red, custom_id="tournament_unregister")
    async def unregister_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            tournament = get_tournament(interaction.guild.id)

            if tournament.max_players == 0:
                return await interaction.response.send_message("❌ No tournament has been created yet.", ephemeral=True)
            if tournament.active:
                return await interaction.response.send_message("⚠️ Tournament already started.", ephemeral=True)

            if tournament.mode == "2v2":
                team_id = get_team_id(interaction.guild.id, interaction.user.id)
                if not team_id:
                    return await interaction.response.send_message("❌ You are not in a team.", ephemeral=True)

                team_members = get_team_members(interaction.guild.id, team_id)
                if not any(member in tournament.players for member in team_members):
                    return await interaction.response.send_message("❌ Your team is not registered.", ephemeral=True)

                # Remove entire team
                for member in team_members:
                    if member in tournament.players:
                        tournament.players.remove(member)

                team_name = get_team_display_name(interaction.guild.id, team_members)

                for item in self.children:
                    if hasattr(item, 'custom_id') and item.custom_id == "participant_count":
                        teams_registered = len(tournament.players) // 2
                        item.label = f"{teams_registered}/{tournament.max_players}"
                        break

                await interaction.response.edit_message(view=self)
                await interaction.followup.send(f"✅ Team {team_name} unregistered! ({len(tournament.players) // 2}/{tournament.max_players} teams)", ephemeral=True)

            else:  # 1v1 mode
                if interaction.user not in tournament.players:
                    return await interaction.response.send_message("❌ You are not registered.", ephemeral=True)

                tournament.players.remove(interaction.user)

                for item in self.children:
                    if hasattr(item, 'custom_id') and item.custom_id == "participant_count":
                        item.label = f"{len(tournament.players)}/{tournament.max_players}"
                        break

                await interaction.response.edit_message(view=self)
                await interaction.followup.send(f"✅ {interaction.user.display_name} unregistered! ({len(tournament.players)}/{tournament.max_players})", ephemeral=True)

            # Update logs when someone unregisters
            await update_logs_message(interaction.guild.id)

        except Exception as e:
            print(f"Error in unregister_button: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ An error occurred. Please try again.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ An error occurred. Please try again.", ephemeral=True)
            except Exception as follow_error:
                print(f"Failed to send error message: {follow_error}")

    @discord.ui.button(label="0/0", style=discord.ButtonStyle.secondary, disabled=True, custom_id="participant_count")
    async def participant_count(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="🚀 Start Tournament", style=discord.ButtonStyle.primary, custom_id="start_tournament")
    async def start_tournament(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            tournament = get_tournament(interaction.guild.id)

            if not has_permission(interaction.user, interaction.guild.id, 'tlr') and not interaction.user.guild_permissions.manage_channels:
                return await interaction.response.send_message("❌ You don't have permission to start tournaments.", ephemeral=True)

            if tournament.max_players == 0:
                return await interaction.response.send_message("❌ No tournament has been created yet.", ephemeral=True)

            if tournament.active:
                return await interaction.response.send_message("❌ Tournament already started.", ephemeral=True)

            # Check minimum requirements
            if tournament.mode == "2v2":
                min_teams = 1  # Need at least 1 team to start
                current_teams = len(tournament.players) // 2
                if current_teams < min_teams:
                    return await interaction.response.send_message("❌ Not enough teams to start tournament (minimum 1 team).", ephemeral=True)
            else:
                if len(tournament.players) < 1:
                    return await interaction.response.send_message("❌ Not enough players to start tournament (minimum 1 player).", ephemeral=True)

            # Add fake players if needed for proper bracket
            if tournament.mode == "2v2":
                # Group players by teams (keep real teams together)
                team_groups = []
                processed_players = set()

                for player in tournament.players:
                    if player in processed_players or isinstance(player, FakePlayer):
                        continue

                    team_id = get_team_id(interaction.guild.id, player.id)
                    if team_id:
                        teammate = get_teammate(interaction.guild.id, player.id)
                        if teammate and teammate in tournament.players:
                            team_groups.append([player, teammate])
                            processed_players.add(player)
                            processed_players.add(teammate)
                        else:
                            # Player has team but teammate not in tournament
                            team_groups.append([player])
                            processed_players.add(player)
                    else:
                        # Player not in a team
                        team_groups.append([player])
                        processed_players.add(player)

                # Add fake player teams
                fake_players = [p for p in tournament.players if isinstance(p, FakePlayer)]
                for i in range(0, len(fake_players), 2):
                    if i + 1 < len(fake_players):
                        team_groups.append([fake_players[i], fake_players[i+1]])

                # Shuffle team order but keep teammates together
                random.shuffle(team_groups)
                tournament.players = []
                for team in team_groups:
                    tournament.players.extend(team)

            else:
                bots_added = 0
                # Add bots one by one until we have an even number of players
                while len(tournament.players) % 2 != 0:
                    bot_name = f"Bot{tournament.fake_count}"
                    bot_id = 761557952975420886 + tournament.fake_count
                    bot = FakePlayer(bot_name, bot_id)
                    tournament.players.append(bot)
                    tournament.fake_count += 1
                    bots_added += 1

                # Shuffle players for 1v1
                random.shuffle(tournament.players)

            tournament.active = True
            tournament.results = []
            tournament.rounds = []

            if tournament.mode == "2v2":
                # Create team pairs for 2v2
                team_pairs = []
                for i in range(0, len(tournament.players), 4):
                    team_a = [tournament.players[i], tournament.players[i+1]]
                    team_b = [tournament.players[i+2], tournament.players[i+3]]
                    team_pairs.append((team_a, team_b))
                tournament.rounds.append(team_pairs)
                current_round = team_pairs
            else:
                round_pairs = [(tournament.players[i], tournament.players[i+1]) for i in range(0, len(tournament.players), 2)]
                tournament.rounds.append(round_pairs)
                current_round = round_pairs

            embed = discord.Embed(
                title=f"🏆 {tournament.title} - Round 1",
                description=f"**Map:** {tournament.map}\n**Abilities:** {tournament.abilities}",
                color=0x3498db
            )

            if tournament.mode == "2v2":
                for i, match in enumerate(current_round, 1):
                    team_a, team_b = match
                    # Get bracket names for team members WITH emojis
                    team_a_display = []
                    team_b_display = []

                    guild_str = str(interaction.guild.id)

                    for player in team_a:
                        player_name = get_player_display_name(player, interaction.guild.id)
                        if guild_str in bracket_roles and str(player.id) in bracket_roles[guild_str] and not isinstance(player, FakePlayer):
                            emojis = ''.join(bracket_roles[guild_str][str(player.id)])
                            player_name = f"{player_name} {emojis}"
                        team_a_display.append(player_name)

                    for player in team_b:
                        player_name = get_player_display_name(player, interaction.guild.id)
                        if guild_str in bracket_roles and str(player.id) in bracket_roles[guild_str] and not isinstance(player, FakePlayer):
                            emojis = ''.join(bracket_roles[guild_str][str(player.id)])
                            player_name = f"{player_name} {emojis}"
                        team_b_display.append(player_name)

                    team_a_str = " & ".join(team_a_display)
                    team_b_str = " & ".join(team_b_display)

                    embed.add_field(
                        name=f"⚔️ Match {i}",
                        value=f"**{team_a_str}** <:VS:1402690899485655201> **{team_b_str}**\n<:Crown:1409926966236283012> Winner: *Waiting...*",
                        inline=False
                    )
            else:
                for i, match in enumerate(current_round, 1):
                    a, b = match
                    # Get bracket names WITH emojis
                    player_a = get_player_display_name(a, interaction.guild.id)
                    player_b = get_player_display_name(b, interaction.guild.id)

                    guild_str = str(interaction.guild.id)
                    if guild_str in bracket_roles and str(a.id) in bracket_roles[guild_str] and not isinstance(a, FakePlayer):
                        emojis = ''.join(bracket_roles[guild_str][str(a.id)])
                        player_a = f"{player_a} {emojis}"

                    if guild_str in bracket_roles and str(b.id) in bracket_roles[guild_str] and not isinstance(b, FakePlayer):
                        emojis = ''.join(bracket_roles[guild_str][str(b.id)])
                        player_b = f"{player_b} {emojis}"

                    embed.add_field(
                        name=f"⚔️ Match {i}",
                        value=f"**{player_a}** <:VS:1402690899485655201> **{player_b}**\n<:Crown:1409926966236283012> Winner: *Waiting...*",
                        inline=False
                    )

            embed.set_footer(text="Use !winner @player to record match results")

            # Create a new view without buttons for active tournament
            active_tournament_view = discord.ui.View()
            await interaction.response.edit_message(embed=embed, view=active_tournament_view)
            tournament.message = None  # Message is edited, not returned

            # Update logs when tournament starts
            await update_logs_message(interaction.guild.id)

        except Exception as e:
            print(f"Error in start_tournament: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ An error occurred. Please try again.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ An error occurred. Please try again.", ephemeral=True)
            except Exception as follow_error:
                print(f"Failed to send error message: {follow_error}")

# Tournament Commands
@bot.command()
async def tournament(ctx):
    """Create a tournament setup panel"""
    embed = discord.Embed(
        title="🏆 Tournament Setup",
        description="Click the button below to configure and create a new tournament!",
        color=0x00ff00
    )
    
    view = TournamentConfigView(ctx.channel)
    await ctx.send(embed=embed, view=view)

@bot.command()
async def winner(ctx, member: discord.Member):
    """Set tournament winner"""
    try:
        await ctx.message.delete()
    except Exception as e:
        print(f"Failed to delete message: {e}")
        pass

    if not has_permission(ctx.author, ctx.guild.id, 'htr') and not has_permission(ctx.author, ctx.guild.id, 'tlr') and not ctx.author.guild_permissions.manage_channels:
        return await ctx.send("❌ You don't have permission to set winners.", delete_after=5)

    tournament = get_tournament(ctx.guild.id)

    if not tournament.active:
        return await ctx.send("❌ No active tournament.", delete_after=5)

    current_round = tournament.rounds[-1]

    # Find and update the match
    match_found = False
    eliminated_players = []
    match_index = -1
    winner_team = None
    loser_team = None

    if tournament.mode == "2v2":
        # Find which team the mentioned member belongs to
        member_team_id = get_team_id(ctx.guild.id, member.id)
        if not member_team_id:
            return await ctx.send("❌ This player is not in a team.", delete_after=5)

        member_team = get_team_members(ctx.guild.id, member_team_id)

        for i, match in enumerate(current_round):
            team_a, team_b = match
            if member in team_a:
                winner_team = team_a
                loser_team = team_b
                tournament.results.append(team_a)
                eliminated_players.extend(team_b)
                match_found = True
                match_index = i
                break
            elif member in team_b:
                winner_team = team_b
                loser_team = team_a
                tournament.results.append(team_b)
                eliminated_players.extend(team_a)
                match_found = True
                match_index = i
                break

        if match_found:
            winner_name = get_team_display_name(ctx.guild.id, winner_team)

    else:  # 1v1 mode
        for i, match in enumerate(current_round):
            a, b = match
            if member == a or member == b:
                tournament.results.append(member)
                eliminated_players.extend([a if member == b else b])
                match_found = True
                match_index = i
                break

        if match_found:
            winner_name = get_player_display_name(member, ctx.guild.id)

    if not match_found:
        return await ctx.send("❌ This player/team is not in the current round.", delete_after=5)
    
    # Add eliminated players to elimination list
    tournament.eliminated.extend(eliminated_players)

    # Update current tournament message to show the winner
    if tournament.message:
        try:
            current_embed = tournament.message.embeds[0]

            # Find and update the specific match field
            if match_index >= 0 and match_index < len(current_embed.fields):
                field = current_embed.fields[match_index]
                if "Match" in field.name:
                    field_value = field.value
                    lines = field_value.split('\n')
                    lines[1] = f"<:Crown:1409926966236283012> Winner: **{get_player_display_name(member, ctx.guild.id)}**"

                    current_embed.set_field_at(match_index, name=field.name, value='\n'.join(lines), inline=field.inline)
                    await tournament.message.edit(embed=current_embed)

        except Exception as e:
            print(f"Error updating tournament message: {e}")

    # Check if round is complete
    if len(tournament.results) == len(current_round):
        if len(tournament.results) == 1:
            # Tournament finished - determine placements and award SP
            winner_data = tournament.results[0]

            # Calculate placements based on elimination order
            all_eliminated = tournament.eliminated

            # Get the final 4 placements
            placements = [] # List of (place, player, sp_reward)

            # 1st place (winner)
            placements.append((1, winner_data, 3))
            if hasattr(winner_data, 'id') and not isinstance(winner_data, FakePlayer):
                add_sp(ctx.guild.id, winner_data.id, 3)

            # 2nd place (last eliminated)
            if len(all_eliminated) >= 1:
                placements.append((2, all_eliminated[-1], 2))
                player = all_eliminated[-1]
                if hasattr(player, 'id') and not isinstance(player, FakePlayer):
                    add_sp(ctx.guild.id, player.id, 2)

            # 3rd and 4th place
            if len(all_eliminated) >= 2:
                placements.append((3, all_eliminated[-2], 1))
                player = all_eliminated[-2]
                if hasattr(player, 'id') and not isinstance(player, FakePlayer):
                    add_sp(ctx.guild.id, player.id, 1)
            if len(all_eliminated) >= 3:
                placements.append((4, all_eliminated[-3], 1))
                player = all_eliminated[-3]
                if hasattr(player, 'id') and not isinstance(player, FakePlayer):
                    add_sp(ctx.guild.id, player.id, 1)

            # Create styled tournament winners embed
            winner_display = get_player_display_name(winner_data, ctx.guild.id)

            embed = discord.Embed(
                title="🏆 Tournament Winners!",
                description=f"Congratulations to **{winner_display}** for winning the\n**{tournament.title}** tournament! 🎉",
                color=0xffd700
            )

            # Add tournament info with custom emojis
            embed.add_field(name="<:map:1409924163346370560> Map", value=tournament.map, inline=True)
            embed.add_field(name="<:abilities:1402690411759407185> Abilities", value=tournament.abilities, inline=True)
            embed.add_field(name="🎮 Mode", value=tournament.mode, inline=True)

            # Create results text
            results_display = ""
            for place, player_obj, sp in placements:
                if place == 1:
                    emoji = "<:Medal_Gold:1402383868505624576>"
                elif place == 2:
                    emoji = "<:Medal_Silver:1402383899597869207>"
                elif place == 3:
                    emoji = "<:Medal_Bronze:1402383923991806063>"
                elif place == 4:
                    emoji = "4️⃣"
                else:
                    emoji = "📍"

                player_str = get_player_display_name(player_obj, ctx.guild.id)
                results_display += f"{emoji} {player_str}\n"

            embed.add_field(name="🏆 Final Rankings", value=results_display, inline=False)

            # Add prizes section with SP
            prize_text = ""
            for place, player_obj, sp in placements:
                if place == 1:
                    emoji = "<:Medal_Gold:1402383868505624576>"
                elif place == 2:
                    emoji = "<:Medal_Silver:1402383899597869207>"
                elif place == 3:
                    emoji = "<:Medal_Bronze:1402383923991806063>"
                elif place == 4:
                    emoji = "4️⃣"
                else:
                    emoji = "📍"

                place_suffix = "st" if place == 1 else "nd" if place == 2 else "rd" if place == 3 else "th"
                prize_text += f"{emoji} {place}{place_suffix}: {sp} Seasonal Points\n"

            embed.add_field(name="🏆 Prizes", value=prize_text, inline=False)

            # Add winner's avatar if it's a real player
            winner_player_obj = winner_data
            if hasattr(winner_player_obj, 'display_avatar') and not isinstance(winner_player_obj, FakePlayer):
                embed.set_thumbnail(url=winner_player_obj.display_avatar.url)

            # Add footer with tournament ID and timestamp
            embed.set_footer(text=f"Tournament completed • {datetime.now().strftime('%d.%m.%Y %H:%M')}")

            # Create a new view without buttons for the completed tournament
            completed_view = discord.ui.View()
            await ctx.send(embed=embed, view=completed_view)

            # Reset tournament
            tournament.__init__()
            
            # Update logs when tournament completes
            await update_logs_message(ctx.guild.id)
            
        else:
            # Create next round with bracket role emojis
            next_round_winners = tournament.results.copy()

            # Add fake players if odd number of winners
            while len(next_round_winners) % 2 != 0:
                bot_name = f"Bot{tournament.fake_count}"
                bot_id = 761557952975420886 + tournament.fake_count
                bot = FakePlayer(bot_name, bot_id)
                next_round_winners.append(bot)
                tournament.fake_count += 1

            next_round_pairs = []
            for i in range(0, len(next_round_winners), 2):
                next_round_pairs.append((next_round_winners[i], next_round_winners[i+1]))

            tournament.rounds.append(next_round_pairs)
            tournament.results = []

            round_num = len(tournament.rounds)
            embed = discord.Embed(
                title=f"🏆 {tournament.title} - Round {round_num}",
                description=f"**Map:** {tournament.map}\n**Abilities:** {tournament.abilities}",
                color=0x3498db
            )

            if tournament.mode == "2v2":
                for i, match in enumerate(next_round_pairs, 1):
                    team_a, team_b = match
                    # Get bracket names for team members WITH emojis
                    team_a_display = []
                    team_b_display = []

                    guild_str = str(ctx.guild.id)

                    for player in team_a:
                        player_name = get_player_display_name(player, ctx.guild.id)
                        if guild_str in bracket_roles and str(player.id) in bracket_roles[guild_str] and not isinstance(player, FakePlayer):
                            emojis = ''.join(bracket_roles[guild_str][str(player.id)])
                            player_name = f"{player_name} {emojis}"
                        team_a_display.append(player_name)

                    for player in team_b:
                        player_name = get_player_display_name(player, ctx.guild.id)
                        if guild_str in bracket_roles and str(player.id) in bracket_roles[guild_str] and not isinstance(player, FakePlayer):
                            emojis = ''.join(bracket_roles[guild_str][str(player.id)])
                            player_name = f"{player_name} {emojis}"
                        team_b_display.append(player_name)

                    team_a_str = " & ".join(team_a_display)
                    team_b_str = " & ".join(team_b_display)

                    embed.add_field(
                        name=f"⚔️ Match {i}",
                        value=f"**{team_a_str}** <:VS:1402690899485655201> **{team_b_str}**\n<:Crown:1409926966236283012> Winner: *Waiting...*",
                        inline=False
                    )
            else:
                for i, match in enumerate(next_round_pairs, 1):
                    a, b = match
                    # Get bracket names WITH emojis for next rounds
                    player_a = get_player_display_name(a, ctx.guild.id)
                    player_b = get_player_display_name(b, ctx.guild.id)

                    guild_str = str(ctx.guild.id)
                    if guild_str in bracket_roles and str(a.id) in bracket_roles[guild_str] and not isinstance(a, FakePlayer):
                        emojis = ''.join(bracket_roles[guild_str][str(a.id)])
                        player_a = f"{player_a} {emojis}"

                    if guild_str in bracket_roles and str(b.id) in bracket_roles[guild_str] and not isinstance(b, FakePlayer):
                        emojis = ''.join(bracket_roles[guild_str][str(b.id)])
                        player_b = f"{player_b} {emojis}"

                    embed.add_field(
                        name=f"⚔️ Match {i}",
                        value=f"**{player_a}** <:VS:1402690899485655201> **{player_b}**\n<:Crown:1409926966236283012> Winner: *Waiting...*",
                        inline=False
                    )

            embed.set_footer(text="Use !winner @player to record match results")

            # Create a new view without buttons for active tournament
            active_tournament_view = discord.ui.View()
            tournament.message = await ctx.send(embed=embed, view=active_tournament_view)

    await ctx.send(f"✅ {winner_name} wins their match!", delete_after=5)

@bot.command()
async def fake(ctx, number: int = 1):
    """Add fake players to tournament"""
    try:
        await ctx.message.delete()
    except:
        pass

    if not has_permission(ctx.author, ctx.guild.id, 'tlr') and not ctx.author.guild_permissions.manage_channels:
        return await ctx.send("❌ You don't have permission to add fake players.", delete_after=5)

    tournament = get_tournament(ctx.guild.id)

    if number < 1 or number > 16:
        return await ctx.send("❌ Number must be between 1 and 16.", delete_after=5)

    if tournament.max_players == 0:
        return await ctx.send("❌ No tournament created yet.", delete_after=5)

    if tournament.active:
        return await ctx.send("❌ Tournament already started.", delete_after=5)

    available_spots = tournament.max_players - len(tournament.players)

    if number > available_spots:
        return await ctx.send(f"❌ Only {available_spots} spots available.", delete_after=5)

    # Create fake players as proper objects
    fake_players = []
    for i in range(number):
        fake_name = f"FakePlayer{tournament.fake_count}"
        fake_id = 761557952975420886 + tournament.fake_count
        fake_player = FakePlayer(fake_name, fake_id)
        fake_players.append(fake_player)
        tournament.fake_count += 1

    tournament.players.extend(fake_players)

    fake_list = ", ".join([f.display_name for f in fake_players])
    await ctx.send(f"🤖 Added {number} fake player{'s' if number > 1 else ''}: {fake_list}\nTotal players: {len(tournament.players)}/{tournament.max_players}", delete_after=10)

    await log_command(ctx.guild.id, ctx.author, "!fake", f"Added {number} fake players")

# Additional Commands from both bots

@bot.command()
async def sp(ctx, member: discord.Member = None, sp_change: int = None):
    """View or manage seasonal points"""
    if member and sp_change is not None:
        # Staff command to add/remove SP
        if not await is_staff(ctx):
            await ctx.send("You don't have permission to modify SP.")
            return
        
        add_sp(ctx.guild.id, member.id, sp_change)
        current_sp = get_sp(ctx.guild.id, member.id)
        action = "added to" if sp_change > 0 else "removed from"
        await ctx.send(f"✅ {abs(sp_change)} SP {action} {member.mention}. Total: {current_sp} SP")
    else:
        # View SP
        if member is None:
            member = ctx.author
        
        current_sp = get_sp(ctx.guild.id, member.id)
        
        embed = discord.Embed(
            title=f"{member.display_name}'s Seasonal Points",
            color=0x00ff00
        )
        embed.add_field(name="Current SP", value=f"{current_sp} points", inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        await ctx.send(embed=embed)

# Role permission commands
@bot.command()
async def htr(ctx, *roles: discord.Role):
    """Set HTR (Host Tournament Role) permissions"""
    if not ctx.author.guild_permissions.manage_guild:
        return await ctx.send("❌ You don't have permission to set HTR roles.", delete_after=5)
    try:
        await ctx.message.delete()
    except Exception as e:
        print(f"Failed to delete message: {e}")
        pass

    if not roles:
        return await ctx.send("❌ Please mention at least one role.", delete_after=5)

    guild_str = str(ctx.guild.id)
    if guild_str not in role_permissions:
        role_permissions[guild_str] = {}

    role_permissions[guild_str]['htr'] = [role.id for role in roles]
    save_data()

    role_mentions = [role.mention for role in roles]
    await ctx.send(f"✅ HTR permissions granted to: {', '.join(role_mentions)}", delete_after=10)

@bot.command()
async def adr(ctx, role: discord.Role):
    """Set ADR (Admin Role) permissions"""
    if not ctx.author.guild_permissions.manage_guild:
        return await ctx.send("❌ You don't have permission to set ADR roles.", delete_after=5)
    try:
        await ctx.message.delete()
    except Exception as e:
        print(f"Failed to delete message: {e}")
        pass

    guild_str = str(ctx.guild.id)
    if guild_str not in role_permissions:
        role_permissions[guild_str] = {}

    role_permissions[guild_str]['adr'] = [role.id]
    save_data()

    await ctx.send(f"✅ ADR permissions granted to: {role.mention}", delete_after=10)

@bot.command()
async def tlr(ctx, *roles: discord.Role):
    """Set TLR (Tournament Leader Role) permissions"""
    if not ctx.author.guild_permissions.manage_guild:
        return await ctx.send("❌ You don't have permission to set TLR roles.", delete_after=5)
    try:
        await ctx.message.delete()
    except Exception as e:
        print(f"Failed to delete message: {e}")
        pass

    if not roles:
        return await ctx.send("❌ Please mention at least one role.", delete_after=5)

    guild_str = str(ctx.guild.id)
    if guild_str not in role_permissions:
        role_permissions[guild_str] = {}

    role_permissions[guild_str]['tlr'] = [role.id for role in roles]
    save_data()

    role_mentions = [role.mention for role in roles]
    await ctx.send(f"✅ TLR permissions granted to: {', '.join(role_mentions)}", delete_after=10)

# Team commands
@bot.command()
async def invite(ctx, member: discord.Member):
    """Invite a user to form a team for 2v2 tournaments"""
    # Check if user already has a team
    existing_team_id = get_team_id(ctx.guild.id, ctx.author.id)
    if existing_team_id:
        await ctx.send("❌ You are already in a team! Use `!leave` to leave your current team first.")
        return
    
    # Check if target user already has a team
    target_team_id = get_team_id(ctx.guild.id, member.id)
    if target_team_id:
        await ctx.send(f"❌ {member.display_name} is already in a team!")
        return
    
    if member == ctx.author:
        await ctx.send("❌ You can't invite yourself!")
        return
    
    if member.bot:
        await ctx.send("❌ You can't invite bots!")
        return
    
    guild_str = str(ctx.guild.id)
    
    # Initialize team invitations if needed
    if guild_str not in team_invitations:
        team_invitations[guild_str] = {}
    
    if str(member.id) not in team_invitations[guild_str]:
        team_invitations[guild_str][str(member.id)] = []
    
    # Check if already invited
    if ctx.author.id in team_invitations[guild_str][str(member.id)]:
        await ctx.send(f"❌ You already sent a team invitation to {member.display_name}!")
        return
    
    # Add invitation
    team_invitations[guild_str][str(member.id)].append(ctx.author.id)
    
    embed = discord.Embed(
        title="🤝 Team Invitation",
        description=f"{member.mention}, {ctx.author.mention} has invited you to form a team for 2v2 tournaments!",
        color=0x00ff00
    )
    embed.add_field(name="How to accept:", value="Use `!accept @user` to accept the invitation", inline=False)
    embed.add_field(name="How to decline:", value="Use `!decline @user` to decline the invitation", inline=False)
    
    await ctx.send(embed=embed)

@bot.command()
async def accept(ctx, member: discord.Member):
    """Accept a team invitation"""
    # Check if user already has a team
    existing_team_id = get_team_id(ctx.guild.id, ctx.author.id)
    if existing_team_id:
        await ctx.send("❌ You are already in a team!")
        return
    
    # Check if inviter already has a team
    inviter_team_id = get_team_id(ctx.guild.id, member.id)
    if inviter_team_id:
        await ctx.send(f"❌ {member.display_name} is already in a team!")
        return
    
    guild_str = str(ctx.guild.id)
    user_str = str(ctx.author.id)
    
    # Check if invitation exists
    if (guild_str not in team_invitations or 
        user_str not in team_invitations[guild_str] or 
        member.id not in team_invitations[guild_str][user_str]):
        await ctx.send(f"❌ You don't have a team invitation from {member.display_name}!")
        return
    
    # Create team
    team_id = create_team(ctx.guild.id, member, ctx.author)
    
    # Remove invitation
    team_invitations[guild_str][user_str].remove(member.id)
    if not team_invitations[guild_str][user_str]:
        del team_invitations[guild_str][user_str]
    
    embed = discord.Embed(
        title="✅ Team Created!",
        description=f"{member.mention} and {ctx.author.mention} are now teammates!",
        color=0x00ff00
    )
    embed.add_field(name="Team ID", value=team_id, inline=True)
    embed.add_field(name="Team Members", value=f"{member.mention}\n{ctx.author.mention}", inline=True)
    
    await ctx.send(embed=embed)

@bot.command()
async def decline(ctx, member: discord.Member):
    """Decline a team invitation"""
    guild_str = str(ctx.guild.id)
    user_str = str(ctx.author.id)
    
    # Check if invitation exists
    if (guild_str not in team_invitations or 
        user_str not in team_invitations[guild_str] or 
        member.id not in team_invitations[guild_str][user_str]):
        await ctx.send(f"❌ You don't have a team invitation from {member.display_name}!")
        return
    
    # Remove invitation
    team_invitations[guild_str][user_str].remove(member.id)
    if not team_invitations[guild_str][user_str]:
        del team_invitations[guild_str][user_str]
    
    await ctx.send(f"❌ You declined the team invitation from {member.mention}.")

@bot.command()
async def leave(ctx):
    """Leave your current team"""
    team_id = get_team_id(ctx.guild.id, ctx.author.id)
    if not team_id:
        await ctx.send("❌ You are not in a team!")
        return
    
    teammate = get_teammate(ctx.guild.id, ctx.author.id)
    
    # Remove team
    remove_team(ctx.guild.id, team_id)
    
    if teammate:
        await ctx.send(f"❌ {ctx.author.mention} left the team. {teammate.mention} is no longer in a team.")
    else:
        await ctx.send("❌ You left your team.")

@bot.command()
async def team(ctx):
    """Check your current team"""
    team_id = get_team_id(ctx.guild.id, ctx.author.id)
    if not team_id:
        await ctx.send("❌ You are not in a team! Use `!invite @user` to create one.")
        return
    
    team_members = get_team_members(ctx.guild.id, team_id)
    
    embed = discord.Embed(
        title="👥 Your Team",
        color=0x00ff00
    )
    embed.add_field(name="Team ID", value=team_id, inline=True)
    
    member_list = "\n".join([member.mention for member in team_members])
    embed.add_field(name="Team Members", value=member_list, inline=True)
    
    await ctx.send(embed=embed)

# Bot events
@bot.event
async def on_ready():
    print(f'{bot.user} has logged in!')
    init_db()
    load_data()
    
    # Add persistent views for buttons to work after restart
    bot.add_view(TournamentView())
    bot.add_view(TournamentConfigView(None))
    
    print("🔧 Bot is ready and all systems operational!")

@bot.event
async def on_member_join(member):
    """Handle new member joins for welcomer system"""
    guild_id = str(member.guild.id)
    
    guild_config = load_json('guild_config.json')
    config = guild_config.get(guild_id, {})
    
    if config.get('welcomer_enabled') and config.get('welcomer_channel'):
        channel = bot.get_channel(config['welcomer_channel'])
        if channel:
            welcome_message = f"Welcome! <@{member.id}> Thanks for joining my server you are **GOAT** <:w_trkis:1400194042234667120> <:GOAT:1400194575125188811>"
            await channel.send(welcome_message)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    # Check for number guessing game
    guild_str = str(message.guild.id)
    if guild_str in active_games and message.channel.id == active_games[guild_str]['channel_id']:
        try:
            guessed_number = int(message.content.strip())
            correct_number = active_games[guild_str]['number']
            
            if guessed_number == correct_number:
                embed = discord.Embed(
                    title="🎉 Congratulations!",
                    description=f"{message.author.mention} guessed the correct number: **{correct_number}**!",
                    color=0x00ff00
                )
                await message.channel.send(embed=embed)
                
                # Award SP for winning
                add_sp(message.guild.id, message.author.id, 1)
                
                # Remove the active game
                del active_games[guild_str]
        except ValueError:
            pass  # Not a number, ignore
    
    await bot.process_commands(message)

# Error handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        await ctx.send("User not found.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Missing required argument: {error.param}")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Invalid argument provided.")
    else:
        print(f"Unhandled error: {error}")

# Additional utility commands
@bot.command()
async def game(ctx, game_range: str):
    """Start a number guessing game"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    # Parse the range (e.g., "1-50")
    try:
        if '-' in game_range:
            min_num, max_num = map(int, game_range.split('-'))
        else:
            await ctx.send("❌ Please use the format: !game 1-50")
            return
        
        if min_num >= max_num or min_num < 1 or max_num > 10000:
            await ctx.send("❌ Invalid range. Use a valid range like 1-50")
            return
        
    except ValueError:
        await ctx.send("❌ Please use the format: !game 1-50")
        return
    
    # Select random number
    selected_number = random.randint(min_num, max_num)
    
    guild_str = str(ctx.guild.id)
    active_games[guild_str] = {
        'number': selected_number,
        'range': [min_num, max_num],
        'channel_id': ctx.channel.id
    }
    
    embed = discord.Embed(
        title="🎲 Number Guessing Game Started!",
        description=f"I've selected a number between **{min_num}** and **{max_num}**!\n\nGuess the number by typing it in chat!",
        color=0xff9500
    )
    embed.set_footer(text=f"Range: {min_num} - {max_num}")
    
    await ctx.send(embed=embed)

# Run the bot
if __name__ == "__main__":
    TOKEN = os.getenv("TOKEN")
    if not TOKEN:
        print("Please set the TOKEN environment variable")
    else:
        keep_alive()
        bot.run(TOKEN)
