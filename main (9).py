import discord
from discord.ext import commands, tasks
import os
import random
import asyncio
import json
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

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
        self.mode = "1v1"  # Can be "1v1" or "2v2"

def get_tournament(guild_id):
    """Get tournament for specific guild"""
    if guild_id not in tournaments:
        tournaments[guild_id] = Tournament()
    return tournaments[guild_id]

# Store user data (all server-specific)
sp_data = {}  # {guild_id: {user_id: sp_amount}}
tournaments = {}  # {guild_id: Tournament}
role_permissions = {}  # {guild_id: {'htr': [role_ids], 'adr': [role_ids], 'tlr': [role_ids]}}
teams = {}  # {guild_id: {team_id: [player1, player2]}}
team_invitations = {}  # {guild_id: {user_id: [inviter_id1, inviter_id2, ...]}}
player_teams = {}  # {guild_id: {user_id: team_id}}
log_channels = {}  # {guild_id: channel_id}

# Game state storage
game_sessions = {}  # {channel_id: {'number': int, 'active': bool}}

# Moderation Database functions
def init_moderation_db():
    """Initialize moderation JSON database files"""
    db_files = {
        'warnings.json': [],
        'user_levels.json': {},
        'guild_config.json': {},
        'level_roles.json': {},
        'automod_warnings.json': {},
        'user_accounts.json': {},
        'tickets.json': []
    }
    
    for filename, default_data in db_files.items():
        if not os.path.exists(filename):
            with open(filename, 'w') as f:
                json.dump(default_data, f)

def load_moderation_json(filename):
    """Load data from moderation JSON file"""
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {} if filename != 'warnings.json' and filename != 'tickets.json' else []

def save_moderation_json(filename, data):
    """Save data to moderation JSON file"""
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)

# Helper functions for moderation
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
        return timedelta(days=amount * 30)  # Approximate
    
    return None

async def is_staff(ctx):
    """Check if user is staff (has manage messages permission or has staff role)"""
    if ctx.author.guild_permissions.manage_messages:
        return True
    
    # Check if user has any staff roles
    guild_config = load_moderation_json('guild_config.json')
    config = guild_config.get(str(ctx.guild.id), {})
    staff_roles = config.get('staff_roles', '')
    
    if staff_roles:
        staff_role_ids = staff_roles.split(',')
        user_role_ids = [str(role.id) for role in ctx.author.roles]
        return any(role_id in staff_role_ids for role_id in user_role_ids)
    
    return False

# Game command helper functions
async def start_game(channel, number_range=(1, 20)):
    """Start a new number guessing game"""
    channel_id = channel.id
    secret_number = random.randint(number_range[0], number_range[1])
    
    game_sessions[channel_id] = {
        'number': secret_number,
        'active': True,
        'range': number_range
    }
    
    return secret_number

async def check_guess(channel, user, guess):
    """Check if a user's guess is correct"""
    channel_id = channel.id
    
    if channel_id not in game_sessions or not game_sessions[channel_id]['active']:
        return None
    
    secret_number = game_sessions[channel_id]['number']
    
    if guess == secret_number:
        game_sessions[channel_id]['active'] = False
        return 'win'
    
    return 'continue'

async def end_game(channel):
    """End the current game in a channel"""
    channel_id = channel.id
    if channel_id in game_sessions:
        game_sessions[channel_id]['active'] = False
        return game_sessions[channel_id]['number']
    return None

def get_player_display_name(player, guild_id=None):
    """Get player display name"""
    if isinstance(player, FakePlayer):
        return player.display_name

    # Priority: nick > display_name > name > str(player)
    base_name = ""
    if hasattr(player, 'user.name') and player.user.name:
        base_name = player.user.name
    elif hasattr(player, 'user.name'):
        base_name = player.user.name
    elif hasattr(player, 'user.name'):
        base_name = player.user.name
    else:
        base_name = str(player)

    return base_name

# Load data
def load_data():
    global sp_data, role_permissions, teams, team_invitations, player_teams, log_channels, bracket_roles
    try:
        with open('user_data.json', 'r') as f:
            data = json.load(f)
            sp_data = data.get('sp_data', {})
            role_permissions = data.get('role_permissions', {})
            log_channels = data.get('log_channels', {})
            bracket_roles = data.get('bracket_roles', {})
            # Teams data is not loaded since it contains Discord objects
            teams = {}
            team_invitations = {}
            player_teams = {}
    except FileNotFoundError:
        pass
    
    # Initialize moderation database
    init_moderation_db()

def save_data():
    data = {
        'sp_data': sp_data,
        'role_permissions': role_permissions,
        'log_channels': log_channels,
        'bracket_roles': bracket_roles
        # Teams are not saved since they contain Discord objects
    }
    with open('user_data.json', 'w') as f:
        json.dump(data, f)

def add_sp(guild_id, user_id, sp):
    guild_str = str(guild_id)
    user_str = str(user_id)

    if guild_str not in sp_data:
        sp_data[guild_str] = {}

    if user_str not in sp_data[guild_str]:
        sp_data[guild_str][user_str] = 0

    sp_data[guild_str][user_str] += sp
    save_data()

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

@bot.event
async def on_ready():
    print(f"✅ Bot is online as {bot.user}")
    load_data()

    # Add persistent views for buttons to work after restart
    bot.add_view(TournamentView())
    bot.add_view(TournamentConfigView(None))
    bot.add_view(HosterRegistrationView())

    print("🔧 Bot is ready and all systems operational!")

class TournamentConfigModal(discord.ui.Modal, title="Tournament Configuration"):
    def __init__(self, target_channel):
        super().__init__()
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

            await interaction.response.send_message("🚀 Starting tournament...", ephemeral=True)

            # Auto-fill with bots to make even number
            if tournament.mode == "2v2":
                current_teams = len(tournament.players) // 2
                # Add bots one by one until we have an even number of teams
                while current_teams % 2 != 0:
                    # Create bot team
                    bot1_name = f"Bot{tournament.fake_count}"
                    bot1_id = 761557952975420886 + tournament.fake_count
                    bot1 = FakePlayer(bot1_name, bot1_id)
                    tournament.fake_count += 1

                    bot2_name = f"Bot{tournament.fake_count}"
                    bot2_id = 761557952975420886 + tournament.fake_count
                    bot2 = FakePlayer(bot2_name, bot2_id)
                    tournament.fake_count += 1

                    tournament.players.extend([bot1, bot2])
                    current_teams += 1

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
                # Add bots one by one until we have an even number of players
                while len(tournament.players) % 2 != 0:
                    bot_name = f"Bot{tournament.fake_count}"
                    bot_id = 761557952975420886 + tournament.fake_count
                    bot = FakePlayer(bot_name, bot_id)
                    tournament.players.append(bot)
                    tournament.fake_count += 1

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
                    # Get bracket names
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
            tournament.message = await interaction.channel.send(embed=embed, view=active_tournament_view)
            await interaction.followup.send("✅ Tournament started successfully!", ephemeral=True)

        except Exception as e:
            print(f"Error in start_tournament: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ An error occurred while starting the tournament.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ An error occurred while starting the tournament.", ephemeral=True)
            except Exception as follow_error:
                print(f"Failed to send error message: {follow_error}")

class TeamInvitationView(discord.ui.View):
    def __init__(self, inviter, invitee, guild_id):
        super().__init__(timeout=300)  # 5 minute timeout
        self.inviter = inviter
        self.invitee = invitee
        self.guild_id = guild_id

    async def on_timeout(self):
        # Disable all buttons when timeout occurs
        for item in self.children:
            item.disabled = True
        try:
            # Try to edit the message to show it timed out
            await self.message.edit(content="❌ Team invitation expired.", view=self)
        except:
            pass

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept_invitation(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invitee.id:
            return await interaction.response.send_message("❌ This invitation is not for you.", ephemeral=True)

        guild_id = self.guild_id
        guild_str = str(guild_id)

        # Check if users are already in teams
        inviter_team = get_team_id(guild_id, self.inviter.id)
        invitee_team = get_team_id(guild_id, self.invitee.id)

        if inviter_team or invitee_team:
            await interaction.response.send_message("❌ One of you is already in a team. Use `!leave_team` first.", ephemeral=True)
            return

        # Create team
        team_id = create_team(guild_id, self.inviter, self.invitee)

        # Remove invitation
        if guild_str in team_invitations and str(self.invitee.id) in team_invitations[guild_str]:
            if self.inviter.id in team_invitations[guild_str][str(self.invitee.id)]:
                team_invitations[guild_str][str(self.invitee.id)].remove(self.inviter.id)

        team_name = get_team_display_name(guild_id, [self.inviter, self.invitee])

        # Disable buttons
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(content=f"✅ Team created: **{team_name}**", view=self)

        # Notify inviter
        try:
            await self.inviter.send(f"✅ {self.invitee.display_name} accepted your team invitation! Team: **{team_name}**")
        except:
            pass

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red)
    async def reject_invitation(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invitee.id:
            return await interaction.response.send_message("❌ This invitation is not for you.", ephemeral=True)

        guild_str = str(self.guild_id)

        # Remove invitation
        if guild_str in team_invitations and str(self.invitee.id) in team_invitations[guild_str]:
            if self.inviter.id in team_invitations[guild_str][str(self.invitee.id)]:
                team_invitations[guild_str][str(self.invitee.id)].remove(self.inviter.id)

        # Disable buttons
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(content="❌ Team invitation rejected.", view=self)

        # Notify inviter
        try:
            await self.inviter.send(f"❌ {self.invitee.display_name} rejected your team invitation.")
        except:
            pass

class HosterRegistrationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    @discord.ui.button(label="Register", style=discord.ButtonStyle.green, custom_id="hoster_register")
    async def register_hoster(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not host_registrations['active']:
            return await interaction.response.send_message("❌ Hoster registration is not active.", ephemeral=True)

        if interaction.user in host_registrations['hosters']:
            return await interaction.response.send_message("❌ You are already registered as a hoster.", ephemeral=True)

        if len(host_registrations['hosters']) >= host_registrations['max_hosters']:
            return await interaction.response.send_message("❌ Maximum number of hosters reached.", ephemeral=True)

        host_registrations['hosters'].append(interaction.user)

        # Update the embed
        embed = discord.Embed(
            title="🎯 Hoster Registration",
            description="Here the hosters will register to host tournaments!",
            color=0x00ff00
        )

        if host_registrations['hosters']:
            hoster_list = ""
            for i, hoster in enumerate(host_registrations['hosters'], 1):
                hoster_name = hoster.nick if hoster.nick else hoster.display_name
                hoster_list += f"{i}. {hoster_name}\n"
            embed.add_field(name="Hosters registered:", value=hoster_list, inline=False)
        else:
            embed.add_field(name="Hosters registered:", value="None yet", inline=False)

        embed.add_field(name="Slots:", value=f"{len(host_registrations['hosters'])}/{host_registrations['max_hosters']}", inline=True)

        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send(f"✅ {interaction.user.display_name} registered as a hoster!", ephemeral=True)

    @discord.ui.button(label="Unregister", style=discord.ButtonStyle.red, custom_id="hoster_unregister")
    async def unregister_hoster(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not host_registrations['active']:
            return await interaction.response.send_message("❌ Hoster registration is not active.", ephemeral=True)

        if interaction.user not in host_registrations['hosters']:
            return await interaction.response.send_message("❌ You are not registered as a hoster.", ephemeral=True)

        host_registrations['hosters'].remove(interaction.user)

        # Update the embed
        embed = discord.Embed(
            title="🎯 Hoster Registration",
            description="Here the hosters will register to host tournaments!",
            color=0x00ff00
        )

        if host_registrations['hosters']:
            hoster_list = ""
            for i, hoster in enumerate(host_registrations['hosters'], 1):
                hoster_name = hoster.nick if hoster.nick else hoster.display_name
                hoster_list += f"{i}. {hoster_name}\n"
            embed.add_field(name="Hosters registered:", value=hoster_list, inline=False)
        else:
            embed.add_field(name="Hosters registered:", value="None yet", inline=False)

        embed.add_field(name="Slots:", value=f"{len(host_registrations['hosters'])}/{host_registrations['max_hosters']}", inline=True)

        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send(f"✅ {interaction.user.display_name} unregistered from hosting.", ephemeral=True)

    @discord.ui.button(label="End Register", style=discord.ButtonStyle.secondary, custom_id="end_hoster_register")
    async def end_registration(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user, interaction.guild.id, 'tlr') and not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("❌ You don't have permission to end registration.", ephemeral=True)

        host_registrations['active'] = False

        # Keep the existing embed but disable all buttons
        embed = discord.Embed(
            title="🎯 Hoster Registration - CLOSED",
            description="Hoster registration has been closed by a moderator.",
            color=0xff0000
        )

        if host_registrations['hosters']:
            hoster_list = ""
            for i, hoster in enumerate(host_registrations['hosters'], 1):
                hoster_name = hoster.nick if hoster.nick else hoster.display_name
                hoster_list += f"{i}. {hoster_name}\n"
            embed.add_field(name="Final Hosters registered:", value=hoster_list, inline=False)
        else:
            embed.add_field(name="Final Hosters registered:", value="None", inline=False)

        embed.add_field(name="Final Slots:", value=f"{len(host_registrations['hosters'])}/{host_registrations['max_hosters']}", inline=True)

        # Disable all buttons
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)

# Global host registrations
host_registrations = {
    'active': False,
    'max_hosters': 0,
        'hosters': [],
    'channel': None,
    'message': None
}

# Bracket roles data
bracket_roles = {}

@bot.command()
async def create(ctx, channel: discord.TextChannel):
    try:
        await ctx.message.delete()
    except Exception as e:
        print(f"Failed to delete message: {e}")
        pass

    if not has_permission(ctx.author, ctx.guild.id, 'tlr') and not ctx.author.guild_permissions.manage_channels:
        return await ctx.send("❌ You don't have permission to create tournaments.", delete_after=5)

    tournament = get_tournament(ctx.guild.id)
    tournament.target_channel = channel

    embed= discord.Embed(
        title="🏆 Tournament Setup",
        description="Press the button to configure the tournament settings.",
        color=0x00ff00
    )

    view = TournamentConfigView(channel)
    await ctx.send(embed=embed, view=view)

    await log_command(ctx.guild.id, ctx.author, "!create", f"Target channel: {channel.mention}")

@bot.command()
async def start(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    if not has_permission(ctx.author, ctx.guild.id, 'tlr') and not ctx.author.guild_permissions.manage_channels:
        return await ctx.send("❌ You don't have permission to start tournaments.", delete_after=5)

    tournament = get_tournament(ctx.guild.id)

    await log_command(ctx.guild.id, ctx.author, "!start", f"Players: {len(tournament.players)}")

    if tournament.max_players == 0:
        return await ctx.send("❌ No tournament has been created yet. Use `!create #channel` first.", delete_after=5)

    if tournament.active:
        return await ctx.send("❌ Tournament already started.", delete_after=5)

    if len(tournament.players) < 2:
        return await ctx.send("❌ Not enough players to start tournament (minimum 2 players).", delete_after=5)

    # Auto-fill with bots to make even number
    if tournament.mode == "2v2":
        current_teams = len(tournament.players) // 2
        bots_added = 0
        # Add bots one by one until we have an even number of teams
        while current_teams % 2 != 0:
            # Create bot team
            bot1_name = f"Bot{tournament.fake_count}"
            bot1_id = 761557952975420886 + tournament.fake_count
            bot1 = FakePlayer(bot1_name, bot1_id)
            tournament.fake_count += 1

            bot2_name = f"Bot{tournament.fake_count}"
            bot2_id = 761557952975420886 + tournament.fake_count
            bot2 = FakePlayer(bot2_name, bot2_id)
            tournament.fake_count += 1

            tournament.players.extend([bot1, bot2])
            current_teams += 1
            bots_added += 1

        if bots_added > 0:
            await ctx.send(f"Adding {bots_added} bot team(s) to make even bracket...", delete_after=5)

        # Group players by teams (keep real teams together)
        team_groups = []
        processed_players = set()

        for player in tournament.players:
            if player in processed_players or isinstance(player, FakePlayer):
                continue

            team_id = get_team_id(ctx.guild.id, player.id)
            if team_id:
                teammate = get_teammate(ctx.guild.id, player.id)
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

        if bots_added > 0:
            await ctx.send(f"Adding {bots_added} bot player(s) to make even bracket...", delete_after=5)

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
        for i, match in enumerate(current_round, 1):
            a, b = match
            # Get bracket names
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

@bot.command()
async def winner(ctx, member: discord.Member):
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
            embed.add_field(name="🎮 Mode", value="1v1", inline=True)

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
        else:
            # Create next round
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

class FakePlayer:
    def __init__(self, name, user_id):
        self.display_name = name
        self.name = name
        self.nick = name
        self.id = user_id
        self.mention = f"@{user_id}" # Fixed mention format

    def __str__(self):
        return self.mention

@bot.command()
async def fake(ctx, number: int = 1):
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
@bot.command()
async def code(ctx, code: str, member: discord.Member = None):
    try:
        await ctx.message.delete()
    except Exception as e:
        print(f"Failed to delete message: {e}")
        pass

    if not has_permission(ctx.author, ctx.guild.id, 'htr') and not has_permission(ctx.author, ctx.guild.id, 'tlr') and not ctx.author.guild_permissions.manage_channels:
        return await ctx.send("❌ You don't have permission to send codes.", delete_after=5)

    tournament = get_tournament(ctx.guild.id)

    if not tournament.active:
        return await ctx.send("❌ No active tournament.", delete_after=5)

    current_round = tournament.rounds[-1]
    match_players = set()

    if member:
        # Find the specific match the member is in and send code ONLY to that match
        target_match = None

        if tournament.mode == "2v2":
            # Find which match the member is in
            for match in current_round:
                team_a, team_b = match
                if member in team_a or member in team_b:
                    target_match = match
                    break
        else:  # 1v1 mode
            for match in current_round:
                a, b = match
                if member == a or member == b:
                    target_match = match
                    break

        if not target_match:
            return await ctx.send("❌ The mentioned player is not in the current round.", delete_after=5)

        # Add only the players from this specific match
        if tournament.mode == "2v2":
            team_a, team_b = target_match
            for player in team_a + team_b:
                if hasattr(player, 'id') and not isinstance(player, FakePlayer):
                    match_players.add(player)
        else:
            a, b = target_match
            for player in [a, b]:
                if hasattr(player, 'id') and not isinstance(player, FakePlayer):
                    match_players.add(player)

    else:
        # No member mentioned - send to ALL players in current round
        for match in current_round:
            if tournament.mode == "2v2":
                team_a, team_b = match
                for player in team_a + team_b:
                    if hasattr(player, 'id') and not isinstance(player, FakePlayer):
                        match_players.add(player)
            else:
                a, b = match
                for player in [a, b]:
                    if hasattr(player, 'id') and not isinstance(player, FakePlayer):
                        match_players.add(player)

    if not match_players:
        return await ctx.send("❌ No real players found to send code to.", delete_after=5)

    # Send code to selected players
    host_name = ctx.author.nick if ctx.author.nick else ctx.author.display_name
    code_message = f"🔐 **The room code is:** ```{code}```\n**Hosted by:** {host_name}"

    sent_count = 0
    failed_players = []

    for player in match_players:
        try:
            await player.send(code_message)
            sent_count += 1
        except discord.Forbidden:
            player_name = player.nick if player.nick else player.display_name
            failed_players.append(player_name)
        except Exception:
            player_name = player.nick if player.nick else player.display_name
            failed_players.append(player_name)

    if member:
        target_info = f" to {member.display_name}'s match players only"
    else:
        target_info = " to all round players"

    if failed_players:
        await ctx.send(f"✅ Code sent to {sent_count} players{target_info} via DM!\n❌ Failed to send to: {', '.join(failed_players)}", delete_after=10)
    else:
        await ctx.send(f"✅ Code sent to {sent_count} players{target_info} via DM!", delete_after=5)

@bot.command()
async def cancel(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    if not has_permission(ctx.author, ctx.guild.id, 'tlr') and not ctx.author.guild_permissions.manage_channels:
        return await ctx.send("❌ You don't have permission to cancel tournaments.", delete_after=5)

    tournament = get_tournament(ctx.guild.id)
    tournament.__init__()
    await ctx.send("❌ Tournament cancelled.", delete_after=5)

    await log_command(ctx.guild.id, ctx.author, "!cancel", "Tournament cancelled")

@bot.command()
async def hosterregist(ctx, max_hosters: int):
    try:
        await ctx.message.delete()
    except:
        pass

    if not has_permission(ctx.author, ctx.guild.id, 'tlr') and not ctx.author.guild_permissions.manage_channels:
        return await ctx.send("❌ You don't have permission to start hoster registration.", delete_after=5)

    if max_hosters < 1 or max_hosters > 20:
        return await ctx.send("❌ Maximum hosters must be between 1 and 20.", delete_after=5)

    host_registrations['active'] = True
    host_registrations['max_hosters'] = max_hosters
    host_registrations['hosters'] = []
    host_registrations['channel'] = ctx.channel

    embed = discord.Embed(
        title="🎯 Hoster Registration",
        description="Here the hosters will register to host tournaments!",
        color=0x00ff00
    )

    embed.add_field(name="Hosters registered:", value="None yet", inline=False)
    embed.add_field(name="Slots:", value=f"0/{max_hosters}", inline=True)

    view = HosterRegistrationView()
    host_registrations['message'] = await ctx.send(embed=embed, view=view)

    await log_command(ctx.guild.id, ctx.author, "!hosterregist", f"Max hosters: {max_hosters}")

@bot.command()
async def bracketrole(ctx, member: discord.Member, emoji1: str, emoji2: str = "", emoji3: str = ""):
    if not ctx.author.guild_permissions.manage_roles:
        return await ctx.send("❌ You don't have permission to set bracket roles.", delete_after=5)
    try:
        await ctx.message.delete()
    except:
        pass

    emojis = [emoji1, emoji2, emoji3]
    # Filter out empty emojis
    emojis = [e for e in emojis if e.strip()]

    if len(emojis) > 3:
        return await ctx.send("❌ You can only set up to 3 emojis!", delete_after=5)

    if len(emojis) == 0:
        return await ctx.send("❌ You must provide at least one emoji!", delete_after=5)

    guild_str = str(ctx.guild.id)
    if guild_str not in bracket_roles:
        bracket_roles[guild_str] = {}

    bracket_roles[guild_str][str(member.id)] = emojis
    save_data()

    emoji_display = ''.join(emojis)
    player_name = member.nick if member.nick else member.display_name

    await ctx.send(f"✅ Bracket role set for {member.mention}! Their bracket name: {player_name} {emoji_display}", delete_after=10)

@bot.command()
async def bracketname(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    guild_str = str(ctx.guild.id)
    if guild_str in bracket_roles and str(ctx.author.id) in bracket_roles[guild_str]:
        emojis = ''.join(bracket_roles[guild_str][str(ctx.author.id)])
        player_name = ctx.author.nick if ctx.author.nick else ctx.author.display_name
        bracket_name = f"{player_name} {emojis}"
    else:
        player_name = ctx.author.nick if ctx.author.nick else ctx.author.display_name
        bracket_name = player_name

    embed = discord.Embed(
        title="🏷️ Your Bracket Name",
        description=f"**Bracket Name:** {bracket_name}",
        color=0x3498db
    )

    try:
        await ctx.author.send(embed=embed)
        await ctx.send("📨 Bracket name sent via DM!", delete_after=3)
    except discord.Forbidden:
        await ctx.send(embed=embed, delete_after=10)

@bot.command()
async def bracketrolereset(ctx, member: discord.Member = None):
    if not ctx.author.guild_permissions.manage_roles:
        return await ctx.send("❌ You don't have permission to reset bracket roles.", delete_after=5)
    try:
        await ctx.message.delete()
    except:
        pass

    if member is None:
        member = ctx.author

    guild_str = str(ctx.guild.id)
    if guild_str in bracket_roles and str(member.id) in bracket_roles[guild_str]:
        del bracket_roles[guild_str][str(member.id)]
        # Clean up guild entry if it becomes empty   
        if not bracket_roles[guild_str]:
            del bracket_roles[guild_str]
        save_data()

        if member == ctx.author:
            await ctx.send("✅ Your bracket role reset! Your emojis have been removed.", delete_after=5)
        else:
            await ctx.send(f"✅ Bracket role reset for {member.mention}! Their emojis have been removed.", delete_after=5)
    else:
        if member == ctx.author:
            await ctx.send("❌ You don't have any bracket emojis set.", delete_after=5)
        else:
            await ctx.send(f"❌ {member.mention} doesn't have any bracket emojis set.", delete_after=5)

# Seasonal Points commands
@bot.command()
async def sp(ctx, member: discord.Member = None):
    try:
        await ctx.message.delete()
    except:
        pass

    if member is None:
        member = ctx.author

    guild_str = str(ctx.guild.id)
    sp = sp_data.get(guild_str, {}).get(str(member.id), 0)

    embed = discord.Embed(
        title="🏆 Seasonal Points",
        description=f"**Player:** {member.display_name}\n**SP:** {sp}",
        color=0xe74c3c
    )

    try:
        await ctx.author.send(embed=embed)
        await ctx.send("📨 SP information sent via DM!", delete_after=3)
    except discord.Forbidden:
        await ctx.send(embed=embed, delete_after=10)

@bot.command()
async def sp_lb(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    guild_str = str(ctx.guild.id)
    guild_sp_data = sp_data.get(guild_str, {})

    # Sort players by SP
    sorted_players = sorted(guild_sp_data.items(), key=lambda x: x[1], reverse=True)[:10]

    embed = discord.Embed(
        title="🏆 Seasonal Points Leaderboard",
        color=0xf1c40f
    )

    if not sorted_players:
        embed.description = "No players have SP yet!"
    else:
        leaderboard_text = ""
        for i, (user_id, sp) in enumerate(sorted_players, 1):
            user = ctx.guild.get_member(int(user_id))
            if user:
                leaderboard_text += f"**{i}.** {user.display_name} - {sp} SP\n"

        embed.description = leaderboard_text

    await ctx.send(embed=embed, delete_after=30)

@bot.command()
async def sp_rst(ctx):
    if not ctx.author.guild_permissions.manage_guild:
        return await ctx.send("❌ You don't have permission to reset seasonal points.", delete_after=5)
    try:
        await ctx.message.delete()
    except:
        pass

    guild_str = str(ctx.guild.id)
    if guild_str in sp_data:
        sp_data[guild_str] = {}
        save_data()
        await ctx.send("✅ All Seasonal Points have been reset for this server!", delete_after=5)
    else:
        await ctx.send("✅ No Seasonal Points to reset in this server!", delete_after=5)

@bot.command()
async def invite(ctx, member: discord.Member):
    try:
        await ctx.message.delete()
    except Exception as e:
        print(f"Failed to delete message: {e}")
        pass

    if member == ctx.author:
        return await ctx.send("❌ You cannot invite yourself!", delete_after=5)

    guild_id = ctx.guild.id
    guild_str = str(guild_id)

    # Check if users are already in teams
    inviter_team = get_team_id(guild_id, ctx.author.id)
    invitee_team = get_team_id(guild_id, member.id)

    if inviter_team:
        return await ctx.send("❌ You are already in a team. Use `!leave_team` first.", delete_after=5)

    if invitee_team:
        return await ctx.send("❌ That user is already in a team.", delete_after=5)

    # Initialize invitation system for guild
    if guild_str not in team_invitations:
        team_invitations[guild_str] = {}

    if str(member.id) not in team_invitations[guild_str]:
        team_invitations[guild_str][str(member.id)] = []

    # Check if invitation already exists
    if ctx.author.id in team_invitations[guild_str][str(member.id)]:
        return await ctx.send("❌ You have already sent a team invitation to this user.", delete_after=5)

    # Add invitation
    team_invitations[guild_str][str(member.id)].append(ctx.author.id)

    # Send DM to invitee
    embed = discord.Embed(
        title="🤝 Team Invitation",
        description=f"**{ctx.author.display_name}** invited you to be their teammate!",
        color=0x00ff00
    )

    view = TeamInvitationView(ctx.author, member, ctx.guild.id)

    try:
        message = await member.send(embed=embed, view=view)
        view.message = message  # Store message reference for timeout handling
        await ctx.send(f"✅ Team invitation sent to {member.display_name}!", delete_after=5)
    except discord.Forbidden:
        # Remove invitation if DM failed
        team_invitations[guild_str][str(member.id)].remove(ctx.author.id)
        await ctx.send(f"❌ Could not send DM to {member.display_name}. They may have DMs disabled.", delete_after=5)

@bot.command()
async def leave_team(ctx):
    try:
        await ctx.message.delete()
    except Exception as e:
        print(f"Failed to delete message: {e}")
        pass

    guild_id = ctx.guild.id
    team_id = get_team_id(guild_id, ctx.author.id)

    if not team_id:
        return await ctx.send("❌ You are not in a team.", delete_after=5)

    team_members = get_team_members(guild_id, team_id)
    teammate = get_teammate(guild_id, ctx.author.id)

    # Check if team is registered in an active tournament
    tournament = get_tournament(guild_id)
    if tournament.active and tournament.mode == "2v2":
        if any(member in tournament.players for member in team_members):
            return await ctx.send("❌ Cannot leave team while registered in an active tournament.", delete_after=5)

    # Remove team
    remove_team(guild_id, team_id)

    # Notify teammate
    if teammate:
        try:
            await teammate.send(f"💔 {ctx.author.display_name} left your team. The team has been dissolved.")
        except:
            pass

    await ctx.send("✅ You left your team. The team has been dissolved.", delete_after=5)

@bot.command()
async def commands2v2(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    embed = discord.Embed(
        title="🤖 2v2 Mode Commands",
    description="Commands specific to 2v2 team tournaments:",
    color=0xe74c3c
    )

    embed.add_field(
        name="🤝 Team Management",
        value="`!invite @user` - Invite a user to be your teammate\n`!leave_team` - Leave your current team",
        inline=False
    )

    embed.add_field(
        name="🏆 Tournament Notes",
        value="• You must be in a team to register for 2v2 tournaments\n• When one teammate registers, the whole team is registered\n• Use `!code <code> @teammate` to send code to a specific match\n• Use `!winner @teammate` to declare your team as winners",
        inline=False
    )

    embed.add_field(
        name="📝 How it Works",
        value="1. Use `!invite @user` to create a team\n2. Both players will see team registration in 2v2 tournaments\n3. Tournaments show team names like 'Player1 & Player2'\n4. Brackets and leaderboards display teams together",
        inline=False
    )

    await ctx.send(embed=embed, delete_after=30)

# Commands list
@bot.command()
async def commands(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    embed = discord.Embed(
        title="🤖 Bot Commands",
        description="Here are available commands based on your permissions:",
        color=0x3498db
    )

    # Check if user has any special permissions
    has_htr = has_permission(ctx.author, ctx.guild.id, 'htr') or has_permission(ctx.author, ctx.guild.id, 'tlr') or ctx.author.guild_permissions.manage_channels
    has_tlr = has_permission(ctx.author, ctx.guild.id, 'tlr') or ctx.author.guild_permissions.manage_channels
    has_admin = ctx.author.guild_permissions.manage_guild

    # For normal members (no special permissions), show only basic commands
    if not has_htr and not has_tlr and not has_admin:
        embed.add_field(
            name="🤝 Available Commands",
            value="`!invite @user` - Invite a user to be your teammate\n`!leave_team` - Leave your current team\n`!sp [@user]` - Check seasonal points\n`!sp_lb` - SP leaderboard\n`!bracketname` - Check your bracket name",
            inline=False
        )
    else:
        # For users with permissions, show all relevant commands
        # Basic commands everyone can use
        embed.add_field(
            name="🤝 Team Commands",
            value="`!invite @user` - Invite a user to be your teammate\n`!leave_team` - Leave your current team\n`!commands2v2` - View 2v2 mode commands",
            inline=False
        )

        embed.add_field(
            name="🏷️ Personal Commands",
            value="`!bracketname` - Check your bracket name\n`!sp [@user]` - Check seasonal points\n`!sp_lb` - SP leaderboard",
            inline=False
        )

        # TLR permissions (Tournament Leader Role)
        if has_tlr:
            embed.add_field(
                name="🏆 Tournament Commands (TLR)",
                value="`!create #channel` - Create tournament (1v1/2v2)\n`!start` - Start tournament\n`!cancel` - Cancel tournament\n`!hosterregist <max>` - Start host registration\n`!fake <number>` - Add fake players",
                inline=False
            )

        # HTR permissions (Host Tournament Role)
        if has_htr:
            embed.add_field(
                name="🎯 Host Commands (HTR)",
                value="`!winner @player` - Set match winner\n`!code <code> [@player]` - Send room code",
                inline=False
            )

        # Admin permissions
        if has_admin:
            embed.add_field(
                name="⚙️ Admin Commands",
                value="`!bracketrole @user emoji1 emoji2 emoji3` - Set bracket emojis\n`!bracketrolereset @user` - Reset bracket role\n`!htr @role` - HTR permissions\n`!adr @role` - ADR permissions\n`!tlr @role` - TLR permissions\n`!sp_add <amount> @user` - Add SP to user\n`!sp_rmv <amount> @user` - Remove SP from user\n`!sp_rst` - Reset all SP\n`!clear` - Clear tournament messages\n`!logs #channel` - Set tournament logs channel",
                inline=False
            )

    await ctx.send(embed=embed, delete_after=30)

# Role permission commands
@bot.command()
async def htr(ctx, *roles: discord.Role):
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

@bot.command()
async def logs(ctx, channel: discord.TextChannel):
    if not ctx.author.guild_permissions.manage_guild:
        return await ctx.send("❌ You don't have permission to set logs channel.", delete_after=5)
    try:
        await ctx.message.delete()
    except Exception as e:
        print(f"Failed to delete message: {e}")
        pass

    guild_str = str(ctx.guild.id)
    log_channels[guild_str] = channel.id
    save_data()

    await ctx.send(f"✅ Tournament logs will now be sent to {channel.mention}", delete_after=10)

    await log_command(ctx.guild.id, ctx.author, "!logs", f"Logs channel set to {channel.mention}")

@bot.command()
async def sp_add(ctx, amount: int, member: discord.Member):
    if not has_permission(ctx.author, ctx.guild.id, 'adr') and not ctx.author.guild_permissions.manage_guild:
        return await ctx.send("❌ You don't have permission to add SP.", delete_after=5)
    try:
        await ctx.message.delete()
    except Exception as e:
        print(f"Failed to delete message: {e}")
        pass

    if amount <= 0:
        return await ctx.send("❌ Amount must be positive.", delete_after=5)

    add_sp(ctx.guild.id, member.id, amount)
    
    guild_str = str(ctx.guild.id)
    total_sp = sp_data.get(guild_str, {}).get(str(member.id), 0)
    
    await ctx.send(f"✅ Added {amount} SP to {member.display_name}! Total SP: {total_sp}", delete_after=10)
    await log_command(ctx.guild.id, ctx.author, "!sp_add", f"Added {amount} SP to {member.display_name}")

@bot.command()
async def sp_rmv(ctx, amount: int, member: discord.Member):
    if not has_permission(ctx.author, ctx.guild.id, 'adr') and not ctx.author.guild_permissions.manage_guild:
        return await ctx.send("❌ You don't have permission to remove SP.", delete_after=5)
    try:
        await ctx.message.delete()
    except Exception as e:
        print(f"Failed to delete message: {e}")
        pass

    if amount <= 0:
        return await ctx.send("❌ Amount must be positive.", delete_after=5)

    guild_str = str(ctx.guild.id)
    user_str = str(member.id)

    if guild_str not in sp_data:
        sp_data[guild_str] = {}
    if user_str not in sp_data[guild_str]:
        sp_data[guild_str][user_str] = 0

    current_sp = sp_data[guild_str][user_str]
    
    if amount > current_sp:
        return await ctx.send(f"❌ {member.display_name} only has {current_sp} SP, cannot remove {amount}.", delete_after=5)

    sp_data[guild_str][user_str] -= amount
    save_data()
    
    new_total = sp_data[guild_str][user_str]
    
    await ctx.send(f"✅ Removed {amount} SP from {member.display_name}! Total SP: {new_total}", delete_after=10)
    await log_command(ctx.guild.id, ctx.author, "!sp_rmv", f"Removed {amount} SP from {member.display_name}")

@bot.command()
async def clear(ctx):
    if not ctx.author.guild_permissions.manage_guild:
        return await ctx.send("❌ You don't have permission to clear messages.", delete_after=5)
    try:
        await ctx.message.delete()
    except Exception as e:
        print(f"Failed to delete message: {e}")
        pass

    # Get messages to delete (tournament and round messages, but keep leaderboard messages)
    messages_to_delete = []
    
    # Look through recent messages in the channel
    async for message in ctx.channel.history(limit=200):
        if message.author == bot.user:
            # Check if message contains tournament/round content but not leaderboard
            if message.embeds:
                embed = message.embeds[0]
                title = embed.title.lower() if embed.title else ""
                
                # Delete tournament registration, round messages, but keep leaderboards and winner announcements
                if any(keyword in title for keyword in ["tournament", "round", "hoster registration"]) and \
                   not any(keyword in title for keyword in ["leaderboard", "winners", "seasonal points"]):
                    messages_to_delete.append(message)
            
            # Also delete tournament setup messages
            elif "tournament setup" in (message.content.lower() if message.content else ""):
                messages_to_delete.append(message)

    # Delete messages in batches
    deleted_count = 0
    for message in messages_to_delete:
        try:
            await message.delete()
            deleted_count += 1
            await asyncio.sleep(0.5)  # Rate limit protection
        except Exception as e:
            print(f"Failed to delete message: {e}")

    await ctx.send(f"✅ Cleared {deleted_count} tournament messages (kept leaderboards).", delete_after=5)
    await log_command(ctx.guild.id, ctx.author, "!clear", f"Deleted {deleted_count} tournament messages")

# =============================================================================
# MODERATION COMMANDS
# =============================================================================

# Event handler for game guessing
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    # Check for number guesses in active games
    channel_id = message.channel.id
    if channel_id in game_sessions and game_sessions[channel_id]['active']:
        try:
            guess = int(message.content.strip())
            game_range = game_sessions[channel_id]['range']
            
            if game_range[0] <= guess <= game_range[1]:
                result = await check_guess(message.channel, message.author, guess)
                
                if result == 'win':
                    embed = discord.Embed(
                        title="🎉 Game Won!",
                        description=f"{message.author.mention} guessed the correct number: **{guess}**!",
                        color=0x00ff00
                    )
                    await message.channel.send(embed=embed)
                    
        except ValueError:
            pass  # Not a number, ignore
    
    await bot.process_commands(message)

@bot.command()
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    """Warn a user"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    warnings = load_moderation_json('warnings.json')
    warning = {
        'user_id': member.id,
        'guild_id': ctx.guild.id,
        'reason': reason,
        'timestamp': datetime.now().isoformat(),
        'warned_by': ctx.author.id
    }
    warnings.append(warning)
    save_moderation_json('warnings.json', warnings)
    
    embed = discord.Embed(
        title="User Warned",
        color=0xffaa00,
        timestamp=datetime.now()
    )
    embed.add_field(name="User", value=member.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=True)
    embed.add_field(name="Warned by", value=ctx.author.mention, inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def warn_history(ctx, member: discord.Member):
    """View user's warning history"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    warnings = load_moderation_json('warnings.json')
    user_warnings = [w for w in warnings if w['user_id'] == member.id and w['guild_id'] == ctx.guild.id]
    
    if not user_warnings:
        await ctx.send(f"{member.mention} has no warnings.")
        return
    
    embed = discord.Embed(
        title=f"Warning History for {member.display_name}",
        color=0x0099ff,
        timestamp=datetime.now()
    )
    
    for i, warning in enumerate(user_warnings[-10:], 1):  # Show last 10 warnings
        embed.add_field(
            name=f"Warning {i}",
            value=f"**Reason:** {warning['reason']}\n**Date:** {warning['timestamp']}",
            inline=False
        )
    
    embed.set_footer(text=f"Total warnings: {len(user_warnings)}")
    await ctx.send(embed=embed)

@bot.command()
async def warn_rmv(ctx, member: discord.Member, number: int):
    """Remove a specific number of warnings from a user"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    warnings = load_moderation_json('warnings.json')
    user_warnings = [w for w in warnings if w['user_id'] == member.id and w['guild_id'] == ctx.guild.id]
    
    if not user_warnings:
        await ctx.send(f"{member.mention} has no warnings to remove.")
        return
    
    # Remove the specified number of most recent warnings
    removed_count = min(number, len(user_warnings))
    user_warnings = user_warnings[:-removed_count]
    
    # Rebuild warnings list without the removed ones
    new_warnings = [w for w in warnings if not (w['user_id'] == member.id and w['guild_id'] == ctx.guild.id)]
    new_warnings.extend(user_warnings)
    save_moderation_json('warnings.json', new_warnings)
    
    await ctx.send(f"Removed {removed_count} warning(s) from {member.mention}.")

@bot.command()
async def mute(ctx, member: discord.Member, time_str: str = None, *, reason="No reason provided"):
    """Mute a user for a specified time (1m to 7d)"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    if not time_str:
        await ctx.send("Please provide a time duration (e.g., 30m, 2h, 1d).")
        return
    
    duration = parse_time(time_str)
    if not duration:
        await ctx.send("Invalid time format. Use m (minutes), h (hours), d (days).")
        return
    
    # Check if duration is within limits (1m to 7d)
    min_duration = timedelta(minutes=1)
    max_duration = timedelta(days=7)
    
    if duration < min_duration or duration > max_duration:
        await ctx.send("Mute duration must be between 1 minute and 7 days.")
        return
    
    try:
        timeout_until = datetime.now() + duration
        await member.timeout(timeout_until, reason=f"Muted by {ctx.author.name}: {reason}")
        
        embed = discord.Embed(
            title="User Muted",
            color=0xff0000,
            timestamp=datetime.now()
        )
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="Duration", value=time_str, inline=True)
        embed.add_field(name="Reason", value=reason, inline=True)
        embed.add_field(name="Muted by", value=ctx.author.mention, inline=True)
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        await ctx.send("I don't have permission to timeout this user.")
    except Exception as e:
        await ctx.send(f"Error muting user: {str(e)}")

@bot.command()
async def unmute(ctx, member: discord.Member):
    """Unmute a user"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    try:
        await member.timeout(None, reason=f"Unmuted by {ctx.author.name}")
        await ctx.send(f"{member.mention} has been unmuted.")
    except discord.Forbidden:
        await ctx.send("I don't have permission to remove timeout from this user.")
    except Exception as e:
        await ctx.send(f"Error unmuting user: {str(e)}")

@bot.command()
async def ban(ctx, member: discord.Member, time_str: str = None, *, reason="No reason provided"):
    """Ban a user (temporarily if time is specified)"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    try:
        await member.ban(reason=f"Banned by {ctx.author.name}: {reason}")
        
        embed = discord.Embed(
            title="User Banned",
            color=0x000000,
            timestamp=datetime.now()
        )
        embed.add_field(name="User", value=str(member), inline=True)
        embed.add_field(name="Reason", value=reason, inline=True)
        embed.add_field(name="Banned by", value=ctx.author.mention, inline=True)
        
        if time_str:
            duration = parse_time(time_str)
            if duration:
                embed.add_field(name="Duration", value=time_str, inline=True)
                asyncio.create_task(schedule_unban(ctx.guild, member, duration))
        
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        await ctx.send("I don't have permission to ban this user.")
    except Exception as e:
        await ctx.send(f"Error banning user: {str(e)}")

async def schedule_unban(guild, member, duration):
    """Schedule automatic unban"""
    await asyncio.sleep(duration.total_seconds())
    try:
        await guild.unban(member, reason="Temporary ban expired")
    except:
        pass

@bot.command()
async def unban(ctx, *, member_name):
    """Unban a user"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    banned_users = [entry async for entry in ctx.guild.bans()]
    
    for ban_entry in banned_users:
        user = ban_entry.user
        if user.name.lower() == member_name.lower() or str(user) == member_name:
            try:
                await ctx.guild.unban(user, reason=f"Unbanned by {ctx.author.name}")
                await ctx.send(f"{user} has been unbanned.")
                return
            except Exception as e:
                await ctx.send(f"Error unbanning user: {str(e)}")
                return
    
    await ctx.send(f"User '{member_name}' not found in ban list.")

@bot.command()
async def lock(ctx, *, args=None):
    """Lock a channel, optionally allowing specific roles"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    channel = ctx.channel
    
    try:
        # Get the @everyone role
        everyone_role = ctx.guild.default_role
        
        # Get current @everyone permissions to preserve visibility
        current_overwrite = channel.overwrites_for(everyone_role)
        
        # Set permissions to deny send_messages while preserving visibility
        await channel.set_permissions(
            everyone_role,
            send_messages=False,
            read_messages=current_overwrite.read_messages  # Preserve current visibility
        )
        
        # Check for any role mentions in the message
        mentioned_roles = ctx.message.role_mentions
        
        # If specific roles are mentioned, allow them to send messages
        if mentioned_roles:
            for role in mentioned_roles:
                role_overwrite = channel.overwrites_for(role)
                await channel.set_permissions(
                    role, 
                    send_messages=True,
                    read_messages=role_overwrite.read_messages  # Preserve current visibility
                )
            
            role_mentions = ', '.join(role.mention for role in mentioned_roles)
            await ctx.send(f"🔒 Channel locked! Only {role_mentions} can send messages.")
        else:
            await ctx.send("🔒 Channel locked for everyone!")
            
    except discord.Forbidden:
        await ctx.send("I don't have permission to modify channel permissions.")
    except Exception as e:
        await ctx.send(f"Error locking channel: {str(e)}")

@bot.command()
async def unlock(ctx):
    """Unlock a channel"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    channel = ctx.channel
    
    try:
        # Get all current overwrites
        current_overwrites = channel.overwrites.copy()
        
        # Remove send_messages permission for all targets that have it set
        for target, overwrite in current_overwrites.items():
            # Check if this overwrite has send_messages set
            if overwrite.send_messages is not None:
                # Remove the send_messages permission by setting it to None
                await channel.set_permissions(target, send_messages=None)
        
        await ctx.send("🔓 Channel unlocked!")
        
    except discord.Forbidden:
        await ctx.send("I don't have permission to modify channel permissions.")
    except Exception as e:
        await ctx.send(f"Error unlocking channel: {str(e)}")

# Account linking system classes
class AccountLinkModal(discord.ui.Modal, title="Link Your Account"):
    def __init__(self):
        super().__init__()

    ign = discord.ui.TextInput(
        label='In-Game Name (IGN)',
        placeholder='Enter your exact Stumble Guys username...',
        required=True,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        user_accounts = load_moderation_json('user_accounts.json')
        key = f"{interaction.guild.id}_{interaction.user.id}"
        
        user_accounts[key] = {
            'ign': self.ign.value,
            'linked_at': datetime.now().isoformat(),
            'user_id': interaction.user.id,
            'guild_id': interaction.guild.id
        }
        
        save_moderation_json('user_accounts.json', user_accounts)
        
        # Give verified role if configured
        guild_config = load_moderation_json('guild_config.json')
        config = guild_config.get(str(interaction.guild.id), {})
        verified_role_id = config.get('verified_role')
        
        if verified_role_id:
            role = interaction.guild.get_role(verified_role_id)
            if role:
                try:
                    await interaction.user.add_roles(role)
                except:
                    pass
        
        embed = discord.Embed(
            title="✅ Account Linked Successfully!",
            description=f"Your account has been linked with IGN: **{self.ign.value}**",
            color=0x00ff00
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

class AccountLinkView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='🔗 Link Account', style=discord.ButtonStyle.primary)
    async def link_account(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AccountLinkModal()
        await interaction.response.send_modal(modal)

class TicketView(discord.ui.View):
    def __init__(self, ticket_types):
        super().__init__(timeout=None)
        self.ticket_types = ticket_types
        
        # Add buttons for each ticket type
        for ticket_type in ticket_types[:25]:  # Discord limit
            button = discord.ui.Button(
                label=ticket_type,
                style=discord.ButtonStyle.secondary,
                custom_id=f"ticket_{ticket_type.lower().replace(' ', '_')}"
            )
            button.callback = self.create_ticket_callback
            self.add_item(button)
    
    async def create_ticket_callback(self, interaction: discord.Interaction):
        # Extract ticket type from button custom_id
        ticket_type = interaction.data['custom_id'].replace('ticket_', '').replace('_', ' ').title()
        await self.create_ticket(interaction, ticket_type)
    
    async def create_ticket(self, interaction: discord.Interaction, ticket_type):
        guild = interaction.guild
        user = interaction.user
        
        # Check if user already has an open ticket
        tickets = load_moderation_json('tickets.json')
        user_tickets = [t for t in tickets if t['user_id'] == user.id and t['guild_id'] == guild.id and not t.get('closed', False)]
        
        if user_tickets:
            channel = guild.get_channel(user_tickets[0]['channel_id'])
            if channel:
                await interaction.response.send_message(
                    f"You already have an open ticket: {channel.mention}",
                    ephemeral=True
                )
                return
        
        # Create ticket channel
        channel_name = f"{ticket_type.lower()}-{user.name}"
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        # Add staff roles to overwrites
        guild_config = load_moderation_json('guild_config.json')
        config = guild_config.get(str(guild.id), {})
        staff_roles = config.get('staff_roles', '')
        
        if staff_roles:
            staff_role_ids = staff_roles.split(',')
            for role_id in staff_role_ids:
                try:
                    role = guild.get_role(int(role_id))
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                except:
                    pass
        
        try:
            ticket_channel = await guild.create_text_channel(
                channel_name,
                overwrites=overwrites
            )
            
            # Save ticket to database
            ticket = {
                'user_id': user.id,
                'guild_id': guild.id,
                'channel_id': ticket_channel.id,
                'ticket_type': ticket_type,
                'created_at': datetime.now().isoformat(),
                'closed': False
            }
            tickets.append(ticket)
            save_moderation_json('tickets.json', tickets)
            
            # Send welcome message in ticket
            embed = discord.Embed(
                title=f"{ticket_type} Ticket",
                description=f"Thank you for opening a ticket, {user.mention}! A staff member will be with you shortly.",
                color=0x0099ff
            )
            await ticket_channel.send(embed=embed)
            
            await interaction.response.send_message(
                f"Ticket created! {ticket_channel.mention}",
                ephemeral=True
            )
            
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to create channels.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Error creating ticket: {str(e)}",
                ephemeral=True
            )

@bot.command()
async def acc(ctx):
    """Display account linking panel"""
    embed = discord.Embed(
        title="🔗 Account Linking System",
        description="**Link your Stumble Guys account to unlock exclusive features!**\n\n🎮 **Benefits of linking:**\n• Get the verified player role\n• Access to exclusive channels\n• Show off your in-game name\n• Participate in events and giveaways\n• Track your progress and stats\n\n📝 **How to link:**\n1. Click the '🔗 Link Account' button below\n2. Enter your exact Stumble Guys username\n3. Confirm your details\n4. Enjoy your new perks!\n\n✅ **Your information is safe** - We only store your in-game name for verification purposes.",
        color=0x0099ff
    )
    
    view = AccountLinkView()
    await ctx.send(embed=embed, view=view)

@bot.command()
async def IGN(ctx, member: discord.Member = None):
    """Show user's in-game name"""
    if member is None:
        member = ctx.author
    
    user_accounts = load_moderation_json('user_accounts.json')
    key = f"{ctx.guild.id}_{member.id}"
    
    if key not in user_accounts:
        await ctx.send(f"{member.mention} hasn't linked their account yet.")
        return
    
    account_data = user_accounts[key]
    ign = account_data['ign']
    linked_at = account_data['linked_at']
    
    embed = discord.Embed(
        title=f"{member.display_name}'s Account",
        color=0x00ff00
    )
    embed.add_field(name="In-Game Name", value=ign, inline=True)
    embed.add_field(name="Linked", value=linked_at, inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    
    await ctx.send(embed=embed)

@bot.command()
async def verified_role(ctx, role: discord.Role):
    """Set the role to give users when they link their account"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("You need administrator permission to use this command.")
        return
    
    guild_config = load_moderation_json('guild_config.json')
    guild_id = str(ctx.guild.id)
    
    if guild_id not in guild_config:
        guild_config[guild_id] = {}
    
    guild_config[guild_id]['verified_role'] = role.id
    save_moderation_json('guild_config.json', guild_config)
    
    await ctx.send(f"Verified role set to {role.mention}! Users will receive this role when they link their account.")

@bot.command()
async def ticket(ctx, *, ticket_types):
    """Create a ticket panel with multiple options"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    # Parse ticket types separated by commas
    types = [t.strip() for t in ticket_types.split(',')]
    
    if len(types) > 25:  # Discord has a limit of 25 buttons per view
        await ctx.send("You can only have up to 25 ticket types.")
        return
    
    embed = discord.Embed(
        title="🎫 Support Tickets System",
        description="**Need assistance?** Click the appropriate button below to create a support ticket!\n\n📋 **How it works:**\n• Click a button that matches your issue\n• A private channel will be created for you\n• Our staff team will assist you promptly\n• Only you and staff can see your ticket\n\n⚠️ **Please note:** You can only have one open ticket at a time.\n\n💡 **Tip:** Be as detailed as possible when describing your issue to help us assist you faster!",
        color=0x0099ff
    )
    
    view = TicketView(types)
    await ctx.send(embed=embed, view=view)

@bot.command()
async def game(ctx, number_range: str = "1-20"):
    """Start a number guessing game"""
    try:
        # Parse the range
        parts = number_range.split('-')
        if len(parts) != 2:
            await ctx.send("Please use format: !game 1-20")
            return
        
        start_num = int(parts[0])
        end_num = int(parts[1])
        
        if start_num >= end_num or start_num < 1 or end_num > 100:
            await ctx.send("Invalid range! Please use a valid range like 1-20 (max 100).")
            return
        
        # Check if there's already an active game
        if ctx.channel.id in game_sessions and game_sessions[ctx.channel.id]['active']:
            await ctx.send("There's already an active game in this channel!")
            return
        
        # Start the game
        secret_number = await start_game(ctx.channel, (start_num, end_num))
        
        embed = discord.Embed(
            title="🎮 Number Guessing Game Started!",
            description=f"I've chosen a number between **{start_num}** and **{end_num}**!\n\n🎯 **How to play:**\n• Just type a number in chat\n• First person to guess correctly wins!\n• Good luck!\n\n🏆 **Prize:** Bragging rights and glory!",
            color=0x00ff00
        )
        embed.set_footer(text="Game is now active! Start guessing!")
        
        await ctx.send(embed=embed)
        
    except ValueError:
        await ctx.send("Please use valid numbers in format: !game 1-20")
    except Exception as e:
        await ctx.send(f"Error starting game: {str(e)}")
    
# Run the bot
if __name__ == "__main__":
    if not TOKEN:
        print("❌ No Discord token found! Please add your bot token to the environment variables.")
        print("Please set DISCORD_TOKEN environment variable with your bot token")
    else:
        try:
            bot.run(TOKEN)
        except Exception as e:
            print(f"❌ Error starting bot: {e}")