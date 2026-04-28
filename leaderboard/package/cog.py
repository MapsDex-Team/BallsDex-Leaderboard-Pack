import asyncio
import inspect
import logging
from typing import TYPE_CHECKING, Any

import discord
from asgiref.sync import sync_to_async
from discord import app_commands
from discord.ext import commands
from django.db.models import Count, Q

from bd_models.enums import PrivacyPolicy
from bd_models.models import Player
from ballsdex.core.utils.menus import ItemFormatter, ListSource, Menu
from ballsdex.core.utils.transformers import BallEnabledTransform, SpecialEnabledTransform
from ballsdex.core.utils.utils import is_staff
from settings.models import settings

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.leaderboard")

# Configuration constants
TOP_PLAYER_LIMIT = [10, 20] # MIN, MAX
ITEMS_PER_PAGE = 5 # How many players are shown on a page
EXCLUDE_IDS = [] # A comma seperated list of User ID's to exclude from the leaderboard
EXCLUDE_BOTS = True # Whether to exclude bots from the leaderboard

class LeaderboardView(discord.ui.LayoutView):
    def __init__(self, interaction: discord.Interaction, **kwargs):
        super().__init__(**kwargs)
        self.interaction = interaction

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message(
                "You cannot use this leaderboard.", ephemeral=True
            )
            return False
        return True


class Leaderboard(commands.Cog):
    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    @app_commands.checks.cooldown(1, 20, key=lambda i: i.user.id)
    @app_commands.choices(
        top=[
            app_commands.Choice(name=str(player_limit), value=player_limit)
            for player_limit in TOP_PLAYER_LIMIT
        ]
    )
    async def leaderboard(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        countryball: BallEnabledTransform | None = None,
        special: SpecialEnabledTransform | None = None,
        currency: bool = False,
        server: bool = False,
        top: int = TOP_PLAYER_LIMIT[0],
    ):
        """
        Show the leaderboard of players.

        Parameters
        ----------
        countryball: BallEnabledTransform
            Only count players with this countryball.
        special: SpecialEnabledTransform
            Only count players with this special.
        currency: bool
            Only count players with currency.
        server: bool
            Only count members of the current server.
        top: int
            Number of players to show.
        """
        staff_check = is_staff(interaction)
        if inspect.isawaitable(staff_check):
            staff_check = await staff_check
        staff = bool(staff_check)
        privacy_bypass_ids = getattr(settings, "inv_privacy_bypass_ids", [])
        privacy_bypass = staff and interaction.channel_id in privacy_bypass_ids

        if currency and (countryball or special):
            await interaction.response.send_message(
                f"Currency and {settings.collectible_name}/special filters are mutually exclusive.",
                ephemeral=True,
            )
            return
        if currency and not getattr(settings, "currency_name", None):
            await interaction.response.send_message(
                "Currency is not enabled on this bot.",
                ephemeral=True,
            )
            return
        if server and interaction.guild is None:
            await interaction.response.send_message(
                "The server option can only be used inside a server.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        try:
            server_member_ids = None
            excluded_ids = set(self.bot.blacklist)
            if not privacy_bypass:
                excluded_ids |= set(EXCLUDE_IDS)
            player_query = Player.objects.exclude(discord_id__in=excluded_ids)
            server_suffix = ""
            use_fallback_filter = False
            if server:
                guild = interaction.guild

                if interaction.client.intents.members:
                    if not guild.chunked:
                        try:
                            await guild.chunk(cache=True)
                        except Exception:
                            log.warning("Could not chunk guild %s (%d)", guild.name, guild.id)

                    server_member_ids = [member.id for member in guild.members]
                    # Fallback to fetch_members if chunking failed to retrieve members
                    if len(server_member_ids) <= 1:
                        try:
                            server_member_ids = [member.id async for member in guild.fetch_members(limit=None)]
                        except Exception:
                            log.exception("Could not fetch members for guild %s (%d)", guild.name, guild.id)
                            server_member_ids = [member.id for member in guild.members]

                    player_query = player_query.filter(discord_id__in=server_member_ids)
                else:
                    use_fallback_filter = True
                server_suffix = "in this server"

            queryset = player_query
            value_attr = "ball_count"
            suffix = ""
            privacy_filtered_leaderboard = False

            if currency:
                queryset = queryset.filter(money__gt=0).order_by("-money")
                subtitle_template = f"Top {{}} richest players {server_suffix}"
                value_name = settings.currency_name.title()
                value_attr = "money"
            elif countryball or special:
                ball_filter = Q(balls__deleted=False)
                title_parts = []
                value_parts = []
                if special:
                    ball_filter &= Q(balls__special_id=special.id)
                    title_parts.append(str(special))
                    value_parts.append(str(special))
                if countryball:
                    ball_filter &= Q(balls__ball=countryball)
                    title_parts.append(str(countryball))
                    value_parts.append(str(countryball))

                privacy_filtered_leaderboard = True
                queryset = queryset.annotate(
                    ball_count=Count("balls", filter=ball_filter)
                ).filter(ball_count__gt=0).order_by("-ball_count")
                label = " ".join(title_parts)
                subtitle_template = f"Top {{}} players with {label}{server_suffix}"
                value_name = " ".join(value_parts)
                suffix = "owned"
            else:
                queryset = queryset.annotate(
                    ball_count=Count("balls", filter=Q(balls__deleted=False))
                ).filter(ball_count__gt=0).order_by("-ball_count")
                subtitle_template = f"Top {{}} players {server_suffix}"
                value_name = settings.plural_collectible_name.title()

            if use_fallback_filter:
                players = []
                offset = 0
                semaphore = asyncio.Semaphore(10)
                interacting_player = None
                if privacy_filtered_leaderboard and not privacy_bypass:
                    interacting_player, _ = await Player.objects.aget_or_create(
                        discord_id=interaction.user.id
                    )

                async def check_player(player: Player) -> Player | None:
                    member = guild.get_member(player.discord_id)
                    if member is not None:
                        if EXCLUDE_BOTS and member.bot:
                            return None
                        return player
                    async with semaphore:
                        try:
                            member = await guild.fetch_member(player.discord_id)
                            if EXCLUDE_BOTS and member.bot:
                                return None
                            return player
                        except Exception:
                            return None

                while len(players) < top:
                    batch_query = queryset[offset : offset + top]
                    batch = await sync_to_async(list)(batch_query)
                    if not batch:
                        break

                    tasks = [check_player(player) for player in batch]
                    results = await asyncio.gather(*tasks)

                    for player in results:
                        if player is None or player in players:
                            continue
                        if privacy_filtered_leaderboard and not privacy_bypass:
                            if player.discord_id == interaction.user.id:
                                players.append(player)
                            elif interacting_player and await player.is_blocked(interacting_player):
                                pass
                            elif player.privacy_policy == PrivacyPolicy.ALLOW:
                                players.append(player)
                        else:
                            players.append(player)

                        if len(players) >= top:
                            break

                    offset += top
            else:
                if not privacy_filtered_leaderboard or privacy_bypass:
                    players = await sync_to_async(lambda: list(queryset[:top]))()
                else:
                    players = []
                    offset = 0
                    interacting_player = None
                    while len(players) < top:
                        batch_query = queryset[offset : offset + top]
                        batch = await sync_to_async(list)(batch_query)
                        if not batch:
                            break

                        if interacting_player is None and any(
                            player.discord_id != interaction.user.id for player in batch
                        ):
                            interacting_player, _ = await Player.objects.aget_or_create(
                                discord_id=interaction.user.id
                            )

                        for player in batch:
                            if player.discord_id == interaction.user.id:
                                players.append(player)
                            elif interacting_player and await player.is_blocked(interacting_player):
                                pass
                            elif player.privacy_policy == PrivacyPolicy.ALLOW:
                                players.append(player)

                            if len(players) >= top:
                                break

                        offset += top

            async def resolve_user(player: Player) -> dict[str, Any] | None:
                if player.discord_id in excluded_ids:
                    return None
                user = self.bot.get_user(player.discord_id)
                if user is None:
                    try:
                        user = await self.bot.fetch_user(player.discord_id)
                    except Exception:
                        user = None

                if EXCLUDE_BOTS and getattr(user, "bot", False):
                    return None

                return {
                    "discord_id": player.discord_id,
                    "user": user,
                    "count": getattr(player, value_attr),
                }

            results = await asyncio.gather(*(resolve_user(player) for player in players))
            entries = []
            for result in results:
                if result is not None:
                    result["rank"] = len(entries) + 1
                    entries.append(result)

            if not entries:
                try:
                    await interaction.edit_original_response(content="No players found.")
                except Exception:
                    pass
                return

            bot_user = interaction.client.user
            pages = []
            for i in range(0, len(entries), ITEMS_PER_PAGE):
                page_sections = []

                for entry_index, entry in enumerate(entries[i : i + ITEMS_PER_PAGE]):
                    rank = entry["rank"]
                    user = entry["user"]
                    discord_id = entry["discord_id"]
                    count = entry["count"]

                    if user is None:
                        mention = f"<@{discord_id}>"
                        thumb = bot_user.display_avatar.url if bot_user is not None else None
                    else:
                        mention = user.mention
                        thumb = user.display_avatar.url

                    suffix_str = f" {suffix}" if suffix else ""

                    section_kwargs: dict[str, Any] = {}
                    if thumb is not None:
                        section_kwargs["accessory"] = discord.ui.Thumbnail(media=thumb)

                    page_sections.append(
                        discord.ui.Section(
                            discord.ui.TextDisplay(
                                content=f"**{rank}. {mention}**"
                            ),
                            discord.ui.TextDisplay(
                                content=(
                                    f"> {value_name}: {count:,}{suffix_str}\n"
                                    f"> User ID: {discord_id}"
                                )
                            ),
                            **section_kwargs,
                        )
                    )

                    # Separator between users, but not after the final user
                    if entry_index < len(entries[i : i + ITEMS_PER_PAGE]) - 1:
                        page_sections.append(
                            discord.ui.Separator(
                                visible=True,
                                spacing=discord.SeparatorSpacing.small,
                            )
                        )

                pages.append(page_sections)

            view = LeaderboardView(interaction)
            header_kwargs: dict[str, Any] = {}
            if bot_user is not None:
                header_kwargs["accessory"] = discord.ui.Thumbnail(media=bot_user.display_avatar.url)

            header = discord.ui.Section(
                discord.ui.TextDisplay(content=f"# {settings.bot_name} Leaderboard"),
                discord.ui.TextDisplay(content=subtitle_template.format(len(players))),
                **header_kwargs,
            )
            container = discord.ui.Container(
                header,
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.large),
            )
            view.add_item(container)

            menu = Menu(
                self.bot,
                view,
                ListSource(pages),
                ItemFormatter(container, position=1),
            )
            await menu.init()

            await interaction.followup.send(
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception:
            log.exception("Error building leaderboard")
            try:
                await interaction.delete_original_response()
            except Exception:
                pass
            raise
