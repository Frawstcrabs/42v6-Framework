# -*- coding: utf-8 -*-

import discord
import re
import difflib

split_blocks = {
    '"': '"',
    "'": "'",
    "«": "»",
    "「": "」",
    "“": "”",
    "‘": "’"
}
bs_escape = "\U00010001"
ec_escape = "\U00010002"


def get_next_arg(content):
    """
    Parse a string for the next argument.
    An argument is defined as either a single word or a string surrounded by
    quote marks. If quote marks are used, the returned argument will have them
    stripped. Quote marks inside a word do not count as separators for
    arguments, and will be considered as part of the word itself. If only the
    opening quote is present, it is considered that everything after the opening
    quote is part of the next argument. If no arguments are left in the string,
    the argument returned will be None.

    :param content: String to search
    :return: Tuple of first arg in string and the content after it,
    left-stripped of whitespace
    """
    new_content = content.lstrip()
    if new_content == "":
        return None, ""
    # replace escaped backslashes with control characters
    new_content = new_content.replace("\\\\", bs_escape)

    search_content = new_content
    search_end = r"(\s|$)"
    end = None
    for start in split_blocks:
        if new_content.startswith(start):
            end = split_blocks[start]
            search_content = search_content[len(start):].replace("\\"+end, ec_escape)
            search_end = end + search_end
            break
        elif new_content.startswith("\\"+start):
            search_content = search_content[1:]
            break
    """
    # for unescaping needlessly escaped start quotes
    else:
        start = None
    """

    ret_search = re.search(fr"^(.*?){search_end}", search_content)

    if ret_search is None:
        # no end character was found, everything is counted as being
        # in quotes
        return search_content, ""
    else:
        if end is None:
            ret = ret_search.group(1).replace(bs_escape, "\\")
            search_content = search_content[ret_search.end(0):]
        else:
            ret = ret_search.group(1)
            arg_length = ret_search.end(0) + (ret.count(ec_escape) * len(end))
            search_content = search_content[arg_length:].replace(ec_escape, "\\"+end)
            ret = ret.replace(bs_escape, "\\").replace(ec_escape, end)
        """
        # for unescaping needlessly escaped start quotes
        if start is not None:
            ret = ret.replace("\\"+start, start)
        """
        return ret, search_content.lstrip()


discrim = re.compile("^(.*?)#([0-9]{4})$")
role_mention = re.compile("^<@&([0-9]{17,18})>$")
user_mention = re.compile("^<@!?([0-9]{17,18})>$")


async def get_member(name, ctx):
    """
    Search for a member's name in the given command context.

    By default, this function will search by, in order:
    - ID
    - User Mention
    - Name#Discriminator
    If none of these match the given name, it will find a list of all members
    whose names or nicknames match the given name. If no matches are found, it
    will check all names/nicknames that vary by at most 5 characters via the
    Levenshtein algorithm. If still no matches are found, return None, else,
    present the list of potential matches to the user and ask them which user
    was intended. If no matches at all are found or the user does not respond
    in time, return None.

    :param name: Member name to match
    :param ctx: Command context
    :return: Member object
    """
    if ctx.guild is None:
        raise RuntimeError("Cannot resolve member in DM")
    guild = ctx.guild

    #  first check is the ID because there is only 1 response if it is
    if name.isdigit():
        found = guild.get_member(int(name))
        if found is not None:
            return found

    #  next up, mentions
    mention = user_mention.match(name)
    if mention is not None:
        member = guild.get_member(int(mention.group(1)))
        return member

    #  then name + discrim
    mention = discrim.match(name)
    if mention is not None:
        member = guild.get_member_named(name)
        if member is not None:
            return member

    #  lastly ID
    if name.isdigit():
        member = guild.get_member(int(name))
        if member is not None:
            return

    #  If we haven't returned at this point, either we have a non-specific
    #  name or a role mention.
    mention = role_mention.match(name)
    if mention is not None:
        role = discord.utils.get(guild.roles, id=int(mention.group(1)))
        if role is not None:
            members = role.members

            if len(members) == 1:
                return members[0]
            elif len(members) == 0:
                return None

            ret = await _get_response_from_member_list(ctx, members)
            return ret
        return None


    members = [m for m in guild.members if m.name == name or m.nick == name]

    if len(members) == 1:
        return members[0]

    if len(members) == 0:
        members = _get_close_members(guild, name)
        if len(members) == 0:
            return None

    match = await _get_response_from_member_list(ctx, members)
    return match


async def _get_response_from_member_list(ctx, matches):
    msg = ["```md", "[0][None]"]
    line = "[{0}][{1.name}#{1.discriminator}]{2}"
    for i, member in enumerate(matches, 1):
        msg.append(line.format(i, member,
            "<"+member.nick+">" if member.nick else ""))
    msg.append("```")
    msg.append(ctx.get_output("MEMBER_RESOLVE_list_footer"))

    if len(msg) > 1950:
        raise CommandError("MEMBER_RESOLVE_list_too_long")

    await ctx.post("\n".join(msg))

    def checker(ret):
        return (ret.channel.id == ctx.channel_id
            and ret.author.id == ctx.author_id
            and ret.content in [str(i) for i in range(len(matches) + 1)])

    ret = await bot.wait_for_message(timeout=10, check=checker)
    if ret is None or ret.content == "0":
        return None
    return matches[int(ret.content) - 1]


def _get_close_members(guild, query):
    names = [m.name for m in guild.members]
    names += [m.nick for m in guild.members if m.nick is not None]

    matches = difflib.get_close_matches(query, names, n=5)
    matches = [m for m in guild.members if m.name in matches or
                                            m.nick and m.nick in matches]

    return matches


from .client import bot
from .command import CommandError
