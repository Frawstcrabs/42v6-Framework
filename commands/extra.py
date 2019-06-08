from .base import bot
import time


@bot.command()
async def hello(ctx):
    start_time = time.time_ns()

    hello_string = ctx.get_output("message", ver="6.0a1") + "\n"
    await ctx.post(hello_string + ctx.get_output("ping"))

    # convert time to ms
    ping_time = (time.time_ns() - start_time) // 1e6

    await ctx.edit(content=hello_string + ctx.get_output("pong", ping_time))

