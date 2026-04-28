import logging
from typing import TYPE_CHECKING

from .cog import Leaderboard

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.leaderboard")


async def setup(bot: "BallsDexBot"):
    log.info("Loading Leaderboard package...")
    cog = Leaderboard(bot)
    await bot.add_cog(cog)

    balls_cog = bot.cogs.get("Balls")
    if balls_cog is not None:
        balls_cog.app_command.command(name="leaderboard")(cog.leaderboard)

    log.info("Leaderboard package loaded successfully!")


async def teardown(bot: "BallsDexBot"):
    balls_cog = bot.cogs.get("Balls")
    if balls_cog is not None:
        balls_cog.app_command.remove_command("leaderboard")
