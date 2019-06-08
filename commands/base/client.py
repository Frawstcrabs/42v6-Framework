# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import json
import re
import time
import warnings
from ast import literal_eval
from asyncio import gather, iscoroutinefunction
from datetime import datetime
from typing import (Any, Awaitable, Callable, Dict, List, Optional, Union,
                    AsyncIterator, overload)
from unittest.mock import sentinel

import discord
from discord import (DMChannel, Embed, Emoji, Guild, Member, Message,
                     PartialEmoji, RawBulkMessageDeleteEvent,
                     RawMessageDeleteEvent, RawMessageUpdateEvent,
                     RawReactionActionEvent, RawReactionClearEvent, Reaction,
                     Role, TextChannel, User, VoiceState, Invite,
                     PermissionOverwrite, CategoryChannel, Permissions, Colour,
                     AuditLogAction, AuditLogEntry, VoiceChannel, File)
from discord.abc import GuildChannel, Messageable, Snowflake
from discord.context_managers import Typing
from discord.guild import BanEntry
from discord.iterators import HistoryIterator
from emoji import UNICODE_EMOJI

NOT_SET = sentinel.NOT_SET



class Ratelimit:
    """
    Auth class for handling rate limits in the bot. This will
    count all invocations of the command from a given user within
    the given time frame, regardless of channel.
    """
    __name__ = "ratelimit"
    def __init__(self, invocations: int, cooldown: int):
        self.invocations = invocations
        self.cooldown = cooldown
        self.rl_calls = {}

    async def __call__(self, ctx: Context):
        user_id = ctx.author_id
        user_calls = self.rl_calls.get(user_id, [])
        call_time = time.time()

        while user_calls and call_time > user_calls[0]:
            user_calls.pop(0)

        if len(user_calls) == self.invocations:
            return False

        user_calls.append(call_time+self.cooldown)
        self.rl_calls[user_id] = user_calls

        return True

ratelimit = Ratelimit


# noinspection PyMethodMayBeStatic
class Bot:
    """
    Class used to control interaction between the program and Discord. It is
    strongly recommend to use the methods provided in this bot than the ones
    included with discord.py's objects, as this allows test fixtures to be more
    easily created for commands.
    """
    FLAG_EMOJI = [literal_eval("\"\\U{0:0>8X}\"".format(0x1F1E6 + i))
                  for i in range(26)]

    def __init__(self, config, *args, **kwargs):
        """
        Initialise the bot object.

        :param config: Dict containing necessary configurations, such as
        the owner id or default invoker.
        :param debug: Optional debug boolean. Disables the bot from sending
        messages except in DMs or in servers it shares with its owner. Note
        that commands will still be processed regardless.
        :param args: Arguments passed directly in discord.AutoShardedClient.
        :param kwargs: Arguments passed directly in discord.AutoShardedClient.
        """
        self.debug: bool = kwargs.pop("debug", False)
        self._bot = discord.AutoShardedClient(*args, **kwargs)

        self.config = config
        self.invoker: str = config.get("invoker", "+")
        self.ping_invokers: List[str] = []
        self._invoker_cache: Dict[int, List[Optional[str]]] = {}
        self.owner: int = config["owner"]
        self.coowners: List[int] = config.get("coowners", []) + [self.owner]

        async def dummy(ctx: Context): pass
        self.root_command = Command("", dummy)
        self.root_command.authorise(CommandToggle())

        # Events
        self.__on_ready_functions = []
        self.__on_error_functions = []
        self.__on_typing_functions = []
        self.__on_message_functions = []
        self.__after_command_functions = []
        self.__on_message_delete_functions = []
        self.__on_bulk_message_delete_functions = []
        self.__on_raw_message_delete_functions = []
        self.__on_raw_bulk_message_delete_functions = []
        self.__on_message_edit_functions = []
        self.__on_raw_message_edit_functions = []
        self.__on_reaction_add_functions = []
        self.__on_raw_reaction_add_functions = []
        self.__on_reaction_remove_functions = []
        self.__on_raw_reaction_remove_functions = []
        self.__on_reaction_clear_functions = []
        self.__on_raw_reaction_clear_functions = []
        # private_channel_create/delete/update/pins_update
        self.__on_guild_channel_create_functions = []
        self.__on_guild_channel_delete_functions = []
        self.__on_guild_channel_update_functions = []
        # guild_channel_pins_update
        # guild_integrations/webhooks_update
        self.__on_member_join_functions = []
        self.__on_member_remove_functions = []
        self.__on_member_update_functions = []
        self.__on_user_update_functions = []
        self.__on_guild_join_functions = []
        self.__on_guild_remove_functions = []
        self.__on_guild_update_functions = []
        self.__on_guild_role_create_functions = []
        self.__on_guild_role_delete_functions = []
        self.__on_guild_role_update_functions = []
        self.__on_guild_emojis_update_functions = []
        # guild un/available
        self.__on_voice_state_update_functions = []
        self.__on_member_ban_functions = []
        self.__on_member_unban_functions = []
        # group_join/remove
        # relationship_add/remove/update

        # Pass login, logout and connect straight through
        self.login = self._bot.login
        self.logout = self._bot.logout
        self.connect = self._bot.connect
        self.wait_until_ready = self._bot.wait_until_ready
        self.change_presence = self._bot.change_presence

    @property
    def user(self):
        return self._bot.user

    def command(self, id_: str = None,
                auths: List[Auth] = None):
        """
        A decorator method for creating a new top-level command.
        This method must both be called and used as a decorator, e.g.::

            @bot.command("id")
            async def example(ctx):
                pass

        :param id_: Command ID, used when searching for response lines and
        acts as a fallback command name.
        :param auths: List of auth functions for the command
        :return: Newly created command object
        """
        return self.root_command.subcommand(id_, auths)

    def global_auth(self, func: Auth):
        """
        Adds an auth that will be called for every command.

        :param func: Auth function
        """
        self.root_command.authorise(func, None)

    def converter(self, *t):
        """
        Create a new converter function.

        Add a wrapper around a regular converter to allow it to
        be used as a type annotation in command definitions.
        This method must both be called and used as a decorator, e.g.::

            @bot.converter()
            def my_converter(arg, ctx):
                pass

        :param t: Types that this converter should represent
        :return: New converter
        """
        def decorate(func: Callable[[str, Context], Any]):
            return add_converter(*t)(func)
        return decorate

    def manual_converter(self, *t):
        """
        Create a new manual converter function.

        Add a wrapper around a manual converter to allow it to
        be used as a type annotation in command definitions.
        Manual converters are expected to manage what arguments
        are popped from the user's command, as well as whether to return
        the default parameter.
        This method must both be called and used as a decorator, e.g.::

            @bot.manual_converter()
            def my_manual_converter(ctx, default):
                pass

        :param t: Types that this converter should represent
        :return: New manual converter
        """
        def decorate(func: Callable[[str, Context], Awaitable[Any]]):
            return add_manual_converter(*t)(func)
        return decorate




    async def invoke(self, message: Message):
        """
        Invoke a command from the given message.

        :param message: Message object from discord
        """
        content = message.content
        if not content: return
        if message.author.bot: return

        if isinstance(message.channel, discord.abc.PrivateChannel):
            invoker = self.invoker
            if not content.startswith(invoker):
                return
        else:
            for inv in await alias.get_alias(message.guild.id):
                if content.startswith(inv):
                    invoker = inv
                    break
            else:
                return
        content = content[len(invoker):].strip()

        ctx = await Context.make(self, message, self.root_command, content,
                                 invoker)

        fail_auth = await ctx.command.invoke(ctx)
        await gather(*[
            func(ctx, fail_auth)
            for func in self.__after_command_functions
        ])


    # =================================================================
    # === Delegate All Stateful Object Functions                    ===
    # =================================================================

    # === Message Objects =============================================
    @staticmethod
    def _check_emoji(text: str) -> bool:
        """
        Check if a string is made up entirely of emojis or whitespace.

        :param text: String to check for emojis
        :return: Boolean of whether the string is all emojis or whitespace
        """
        if not text:
            return False

        char_list = list(text)
        while char_list:
            i = len(text) - len(char_list)
            char = char_list.pop(0)
            if char.strip() == "":
                continue
            if char == "<":
                discord_check = re.search(
                    r"<a?:[a-z0-9_]{2,32}:[0-9]{17,19}>.*?",
                    text[i:],
                    flags=re.I
                )
                if discord_check:
                    emoji_len = discord_check.end()-discord_check.start()
                    char_list = char_list[emoji_len-1:]
                    continue
                else:
                    return False
            if char in Bot.FLAG_EMOJI:
                continue
            if char not in UNICODE_EMOJI:
                return False
        return True

    def clean_message_content(self, content: str, embed: Embed = None) -> str:
        """
        Filter a string to ensure that it contains no @here or @everyone pings,
        and if the embed parameter is None, will replace the content with a
        default message to prevent sending an empty string.

        :param content: String to filter
        :param embed: Optional embed that will be sent with the message
        :return: Filtered string
        """
        if not isinstance(content, str) and content is not None:
            raise TypeError("Content must be string!")

        if embed is not None:
            if content == "":
                content = None
        else:
            if content in [None, ""]:
                content = "Empty Message"

        if content is not None:
            content = content.replace("@here", "@\u200bhere") \
                             .replace("@everyone", "@\u200beveryone")

            if not (content.startswith("```") or self._check_emoji(content)):
                content = "\u200b" + content

            if len(content) > 2000:
                content = content[:1994] + "..."
                if content.count("```") % 2 == 1:
                    content += "```"

        return content

    async def raw_send_message(self, channel_id: int, content: Optional[str],
                               *, embed: Optional[Embed] = None) -> int:
        """
        Send a message to a channel by its ID, in the case that the channel
        object to send to was garbage collected.

        :param channel_id: ID of channel to send to
        :param content: Content of message
        :param embed: Optional message embed
        :return: ID of the sent message
        """
        content = self.clean_message_content(content, embed)

        if embed is not None:
            embed = embed.to_dict()

        data = await self._bot.http.send_message(channel_id, content,
                                                 embed=embed)

        return int(data["id"])

    async def raw_send_files(self, channel_id: str, *, files: List[File],
                             content: str = None, embed: Embed = None) -> int:
        """
        Send a message with files to a channel by its ID, in the case that the
        channel object to send to was garbage collected.

        :param channel_id: ID of channel to send to
        :param files: List of file objects to send
        :param content: Content of message
        :param embed: Optional message embed
        :return: ID of the sent message
        """
        if embed is not None:
            embed = embed.to_dict()

        data = await self._bot.http.send_files(channel_id, files=files,
                                               content=content, embed=embed)

        return int(data["id"])

    async def send_message(self, dest: Messageable, content: Optional[str],
                           *, embed: Optional[Embed] = None,
                           swallow_errors: bool = False) -> Optional[Message]:
        """
        Send a message to a channel.

        Send a message to a channel. If bot.debug is set to True and the dest
        parameter is not a DM or in a server that the owner shares, do nothing.
        If swallow_errors is set to True, any discord Forbidden errors will not
        be raised.

        :param dest: Messageable object to send to
        :param content: Message content
        :param embed: Optional embed object
        :param swallow_errors: Boolean of whether to not raise Forbidden errors
        :return: Newly created message object that was sent
        """

        # Do not send messages to servers in debug mode.
        if (self.debug and
                isinstance(dest, discord.TextChannel) and
                dest.guild.get_member(self.owner) is not None):
            return None

        if not isinstance(dest, discord.abc.Messageable):
            raise TypeError("Cannot send to non-messageable class "
                            f"{type(dest)}")

        content = self.clean_message_content(content, embed)

        try:
            msg = await dest.send(content, embed=embed)
        except discord.errors.Forbidden:
            if swallow_errors:
                return None
            else:
                raise

        # TODO: handle_verbose(msg)
        return msg

    async def edit_message(self, message: Message, **params):
        """
        Edits a message.

        Edits a message to change its content or embed. Options that are not set
        will not be altered.

        :param message: Message to edit
        :param params: Keyword arguments content or embed, containing what to
        replace in the message with.
        """
        if "content" in params:
            params["content"] = self.clean_message_content(params["content"],
                                                           params.get("embed"))
        return await message.edit(**params)

    async def raw_edit_message(self, channel_id: int, message_id: int,
                               content: str = NOT_SET, embed: Embed = NOT_SET):
        """
        Edits a message by it and its channel's IDs, in the case that the
        channel or message objects were garbage collected.

        :param channel_id: ID of channel containing message
        :param message_id: ID of message to edit
        :param content: New content of message
        :param embed: New message embed
        """
        params = {}
        if content is not NOT_SET:
            params["content"] = content
        if embed is not NOT_SET:
            params["embed"] = embed.to_dict()

        await self._bot.http.edit_message(channel_id, message_id, **params)

    @staticmethod
    async def delete_message(message: Message):
        """
        Deletes a message.

        :param message: Message to delete
        """
        await message.delete()

    async def delete_messages(self, *messages: Message):
        channel: TextChannel = messages[0].channel
        if not all(msg.channel == channel for msg in messages):
            raise ValueError("All messages must be in the same channel")
        await channel.delete_messages(messages)

    async def raw_delete_message(self, channel_id: int,
                                 message_id: Union[int, List[int]]):
        """
        Deletes a messages via it and its channel's IDs, in the case that
        the channel or message objects were garbage collected.

        :param channel_id: ID of channel the message is in
        :param message_id: ID of message to delete
        """
        if isinstance(message_id, list):
            if len(message_id) == 1:
                message_id = message_id[0]
            else:
                await self._bot.http.delete_messages(channel_id, message_id)
                return

        await self._bot.http.delete_message(channel_id, message_id)

    @staticmethod
    async def pin_message(message: Message):
        """
        Pins a message.

        :param message: Message to pin.
        """
        await message.pin()

    @staticmethod
    async def unpin_message(message: Message):
        """
        Unpins a message.

        :param message: Message to unpin
        """
        await message.unpin()

    async def raw_pin_message(self, channel_id: int, message_id: int):
        """
        Pins a message via it and its channel's IDs, in the case that
        the channel or message objects were garbage collected.

        :param channel_id: ID of channel the message is in
        :param message_id: ID of message to pin
        """
        await self._bot.http.pin_message(channel_id, message_id)

    async def raw_unpin_message(self, channel_id: int, message_id: int
                                ) -> None:
        """
        Unpins a message via it and its channel's IDs, in the case that
        the channel or message objects were garbage collected.

        :param channel_id: ID of channel the message is in
        :param message_id: ID of message to unpin
        """
        await self._bot.http.unpin_message(channel_id, message_id)

    @staticmethod
    async def add_reaction(message: Message, emoji: ReactionEmoji):
        """
        Adds a reaction to a message.

        :param message: Message to react to
        :param emoji: Emoji to react with
        """
        await message.add_reaction(emoji)

    async def raw_add_reaction(self, channel_id: int, message_id: int,
                               emoji: ReactionEmoji):
        """
        Adds a reaction to a message via it and its channel's IDs, in the case
        that either object was garbage collected.

        :param channel_id: ID of channel containing message
        :param message_id: ID of message
        :param emoji: Emoji to react with
        """
        emoji = Message._emoji_reaction(emoji)
        await self._bot.http.add_reaction(channel_id, message_id, emoji)

    @staticmethod
    async def clear_reactions(message: Message):
        """
        Clears a message's reactions.

        :param message: Message whose reactions will be removed
        """
        await message.clear_reactions()

    async def raw_clear_reactions(self, channel_id, message_id):
        """
        Clears a message's reactions via it and its channel's IDs, in the case
        that either object was garbage collected.

        :param channel_id: ID of channel containing message
        :param message_id: ID of message
        """
        await self._bot.http.clear_reactions(channel_id, message_id)

    @staticmethod
    async def remove_reaction(message: Message, emoji: ReactionEmoji,
                              member: Snowflake):
        """
        Removes a specific member's reaction to a message.

        :param message: Message to remove the reaction of
        :param emoji: Emoji of the reaction
        :param member: User whose reaction to remove
        """
        await message.remove_reaction(emoji, member)

    async def raw_remove_reaction(self, channel_id: int, message_id: int,
                                  emoji: ReactionEmoji, member_id: int):
        """
        Removes a specific member's reaction from a message via the relevant
        IDs, in the case that the necessary objects were garbage collected.

        :param channel_id: ID of channel containing message
        :param message_id: ID of message
        :param emoji: Emoji used in reaction to remove
        :param member_id: ID of member that reacted
        """
        emoji = Message._emoji_reaction(emoji)
        if member_id == self._bot.user.id:
            await self._bot.http.remove_own_reaction(channel_id, message_id,
                                                     emoji)
        else:
            await self._bot.http.remove_reaction(channel_id, message_id,
                                                 emoji, member_id)

    @staticmethod
    async def get_message(channel: Messageable, message_id: int
                          ) -> Awaitable[Message]:
        """
        Retrieves a message object from a channel by it's ID.

        :param channel: Channel object to retrieve the message from
        :param message_id: ID of message to retrieve
        :return: Found message object
        """
        return await channel.fetch_message(message_id)

    @staticmethod
    def logs_from(channel: Messageable, *, limit: int = 100,
                  before: MessageBound = None, after: MessageBound = None,
                  around: MessageBound = None, oldest_first: bool
                  ) -> HistoryIterator:
        """
        Retrieve messages from a channel, returning an iterator.

        :param channel: Channel to retrieve from.
        :param limit: Maximum number of messages to return.
        :param before: Time bound before which each message must have been
        posted.
        :param after: Time bound after which each message must have been
        posted.
        :param around: Time bound around which each message must have been
        sent.
        :param oldest_first: Boolean of whether to return the messages from
        oldest to latest. By default, messages will be returned from latest to
        oldest.
        :return: Iterator object for the message objects
        """
        return channel.history(limit=limit, before=before, after=after,
                               around=around, oldest_first=oldest_first)

    @staticmethod
    def typing_in(channel: Messageable) -> Typing:
        """
        Sends a typing signal in a channel.

        This method should be used as a context manager, e.g.
        with bot.typing_in(channel):
            ...

        :param channel: Channel to type in
        """
        return channel.typing()

    @staticmethod
    async def get_pinned_messages(channel: Messageable) -> List[Message]:
        """
        Find all pinned messages in a channel.

        :param channel: Channel to search in
        :return: List of all pinned messages
        """
        return await channel.pins()

    # = Client Object =================================================

    async def edit_bot_user(self, *, username: str = NOT_SET,
                            avatar: Union[str, bytes] = NOT_SET):
        """
        Edits the discord bot's user object. At least one of username or avatar
        must be set.

        :param username: Optional new username for user
        :param avatar: Optional new avatar for user
        """
        if isinstance(avatar, str):
            with open(avatar, "rb") as file:
                avatar = file.read()

        kwargs = {}
        if username is not NOT_SET:
            kwargs["username"] = username
        if avatar is not NOT_SET:
            kwargs["avatar"] = avatar

        if not kwargs:
            raise ValueError("No changes requested.")

        await self._bot.user.edit(**kwargs)

    # TODO: Add overrides once Literal[] types are added
    # @override
    # async def wait_for(event: Literal["message"], *, check, timeout
    #                    ) -> Message: ...
    # etc
    async def wait_for(self, event: str, *,
                       check: Optional[Callable[[...], bool]] = None,
                       timeout: Optional[float] = None) -> Any:
        """
        Waits for a message or reaction.

        For more details, please find the documentation of Client.wait_for()
        in discord.py, this is literally just a wrapper around it.

        :param event: String of either "message" or "reaction"
        :param check: Predicate to run on each object
        :param timeout: Time limit after which an error will be raised
        :return: Object for which the predicate returned true
        """
        return await self._bot.wait_for(event, check=check, timeout=timeout)

    async def wait_for_message(self, *, author: Optional[User] = None,
                               channel: Union[TextChannel, DMChannel] = None,
                               content: Optional[str] = None,
                               content_contains: Optional[str] = None,
                               check: Optional[Callable[[Message], bool]] = None,
                               timeout: Optional[float] = None
                               ) -> Optional[Message]:
        """
        Waits until a specific message is posted.

        This function will check against the given parameters if not None, then
        return the first found message that matches all of them. If timeout is
        set to a number, this method will return None if the time limit is
        exceeded.

        :param author: Message author
        :param channel: Channel of message
        :param content: Exact content of message
        :param content_contains: Substring of message content
        :param check: Predicate function run on each message
        :param timeout: Time limit after which the method will return None
        :return: Found message object
        """
        def preq(message):
            result = True
            if author is not None:
                result &= message.author == author
            if channel is not None:
                result &= message.channel == channel

            if content is not None:
                result &= message.content == content
            if content_contains is not None:
                result &= content_contains in message.content

            if check is not None:
                result &= check(message)

            return result

        try:
            return await self.wait_for("message", check=preq, timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def wait_for_reaction(self, emoji: Optional[ReactionEmojiList] = None,
                                *, user: Optional[User] = None,
                                message: Optional[Message] = None,
                                check: Optional[Callable[
                                    [RawReactionActionEvent], None]] = None,
                                timeout: Optional[float] = None):
        """
        Waits until a specific reaction is sent.

        This function will check against the given parameters if not None, then
        return the first found reaction that matches all of them. If timeout is
        set to a number, this method will return None if the time limit is
        exceeded.

        :param emoji: Emoji of the reaction
        :param user: User to post the reaction
        :param message: Message to be reacted at
        :param check: Predicate to run on all reactions
        :param timeout: Time limit after which the method will return None
        :return: First found reaction
        """
        # Reaction add will not work if the message leaves the deque.
        # This ensures the message will always be found.

        if emoji is None:
            emoji_check = lambda p: True
        elif isinstance(emoji, str):
            emoji_check = lambda p: p.name == emoji
        elif isinstance(emoji, Emoji):
            emoji_check = lambda p: p.id == emoji.id
        else:
            emoji = [ele if isinstance(ele, str) else ele.id for ele in emoji]
            emoji_check = lambda p: (p.name in emoji or
                                     p.id in emoji)

        def preq(payload: RawReactionActionEvent):
            result = emoji_check(payload.emoji)

            if user is not None:
                result &= payload.user_id == user.id
            if message is not None:
                result &= payload.message_id == message.id
            if check is not None:
                result &= check(payload)

            return result

        try:
            return await self.wait_for("raw_reaction_add", check=preq,
                                       timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def fetch_invite(self, url: str) -> Invite:
        """
        Creates an invite object from a url.

        :param url: URL of invite
        :return: Invite object
        """
        return await self._bot.fetch_invite(url)

    async def fetch_user(self, user_id: int) -> User:
        """
        Retrieve a user object by its ID.

        :param user_id: ID of user to retrieve
        :return: User object
        """
        return await self._bot.fetch_user(user_id)

    async def request_offline_members(self, *guilds: Guild,
                                      very_large: bool = False) -> bool:
        """
        Requests all offline members from the given guilds.
        If the number of members in a guild is greater than 2500, the arg
        very_large must be set to True, or the members will not be requested for
        any of the guilds.

        :param guilds: Guilds to request
        :param very_large: Boolean of whether to allow very large guilds to be
        requested
        :return: Boolean of whether offline members were successfully requested
        """
        for guild in guilds:
            if guild.member_count > 2500 and not very_large:
                warnings.warn("To chunk guilds larger than 2500 members, pass"
                              " very_large=True", UserWarning)
                return False

        await self._bot.request_offline_members(*guilds)
        return True

    # === Guild Object ================================================

    async def create_text_channel(self, guild: Guild, name: str, *,
                                  overwrites: Dict[Union[Role, Member],
                                                   PermissionOverwrite] = None,
                                  category: CategoryChannel = None,
                                  position: int = NOT_SET,
                                  topic: str = NOT_SET, nsfw: bool = False,
                                  slowmode_delay: int = NOT_SET,
                                  reason: str = NOT_SET):
        """
        Creates a new text channel in a guild. Any parameters that are not set
        will not be altered.

        :param guild: Guild to create the channel in
        :param name: Name of channel
        :param overwrites: Dict of permission overwrites for specific members
        :param category: Category to create the new channel in (None to create
        it outside of all categories)
        :param position: Position the new channel should be created in
        :param topic: Channel topic string
        :param nsfw: Boolean of whether this channel is NSFW
        :param slowmode_delay: Slowmode delay timer
        :param reason: Reason for creating channel (used in audit logs)
        """
        kwargs = {
            "name": name,
            "overwrites": overwrites,
            "nsfw": nsfw
        }
        for name, param in (("category", category), ("position", position),
                            ("topic", topic), ("reason", reason),
                            ("slowmode_delay", slowmode_delay)):
            if param is not NOT_SET:
                kwargs[name] = param

        await guild.create_text_channel(**kwargs)

    async def create_role(self, guild: Guild, name: str, *,
                          permissions: Permissions = NOT_SET,
                          colour: Colour = NOT_SET, hoist: bool = False,
                          mentionable: bool = False,
                          reason: str = NOT_SET):
        """
        Creates a new role in a guild. Any parameters that are not set will not
        be altered.

        :param guild: Guild to create new role in
        :param name: Name of role
        :param permissions: Permissions the role will have
        :param colour: Name colour for those that have the role
        :param hoist: Boolean of whether this role should hoist
        :param mentionable: Boolean of whether this role is mentionable
        :param reason: Reason for creation (used in audit logs)
        """
        kwargs = {
            "name": name,
            "hoist": hoist,
            "mentionable": mentionable
        }
        for name, param in (("permissions", permissions), ("colour", colour),
                            "reason", reason):
            if param is not NOT_SET:
                kwargs[name] = param

        await guild.create_role(**kwargs)

    async def estimate_pruned_members(self, guild: Guild, days: int) -> int:
        """
        Estimate the number of pruned members in a guild.

        :param guild: Guild to estimate in
        :param days: Number of days to prune
        :return: Count of all members that would be pruned
        """
        return await guild.estimate_pruned_members(days=days)

    async def fetch_guild_ban(self, guild: Guild, user: Snowflake
                              ) -> BanEntry:
        """
        Retrieve the ban entry of a given user.

        :param guild: Guild to search in
        :param user: User that was banned
        :return: BanEntry object
        """
        return await guild.fetch_ban(user)

    async def get_guild_member(self, guild: Guild, member_id: int) -> Member:
        """
        Retrieve a member from a guild by its ID. If the member does not exist,
        return None.

        :param guild: Guild to search
        :param member_id: Member ID to search by
        :return: Member object (None if no member found)
        """
        member = guild.get_member(member_id)
        if member is None:
            # Guild is not chunked, check elsewhere.
            member = guild.fetch_member(member_id)
        return member

    async def get_guild_invites(self, guild: Guild) -> List[Invite]:
        """
        Retrieve a list of all invites in a guild

        :param guild: Guild to search
        :return: List of all invite objects
        """
        return await guild.invites()

    async def kick_member(self, guild: Guild, member: Snowflake,
                          reason: str = None):
        """
        Kick a member from a guild.

        :param guild: Guild to kick from
        :param member: Member to kick
        :param reason: Reason for kicking (used in audit log)
        """
        await guild.kick(member, reason=reason)

    async def leave_guild(self, guild: Guild):
        """
        Leave a guild.

        :param guild: Guild to leave
        """
        await guild.leave()

    async def unban_member(self, guild: Guild, user: Snowflake,
                           reason: str = None):
        """
        Unban a member from a guild.

        :param guild: Guild to unban from
        :param user: User to unban
        :param reason: Reason for unbanning (used in audit log)
        """
        await guild.unban(user, reason=reason)

    async def get_audit_entry(self, guild: Guild, limit: int = 100,
                              before: Union[Snowflake, datetime] = None,
                              after: Union[Snowflake, datetime] = None,
                              oldest_first: bool = None,
                              user: Snowflake = None,
                              action: AuditLogAction = None
                              ) -> AsyncIterator[AuditLogEntry]:
        """
        Retrieve an async iterator of the audit logs in a guild.

        :param guild: Guild to retrieve from
        :param limit: Maximum number of logs to retrieve
        :param before: Time before which the logs must be sent
        :param after: Time after which the logs must be sent
        :param oldest_first: Boolean of whether to return the logs from oldest
        to latest. By default, they will be sent latest first.
        :param user: Moderator to filter entries with
        :param action: Audit action to filter entries with
        :return: Iterator of selected logs
        """
        return guild.audit_logs(limit=limit, after=after, before=before,
                                oldest_first=oldest_first, user=user,
                                action=action)

    async def get_vanity_invite(self, guild: Guild) -> Invite:
        """
        Retrieve the vanity invite of a guild.

        :param guild: Guild to retrieve from
        :return: Invite object of vanity invite
        """
        return await guild.vanity_invite()

    # === Member Object ===============================================

    async def ban_member(self, member: Union[Member, User, int],
                         guild: Guild = None, delete_days: int = 0,
                         reason: str = None):
        """
        Ban a member from a guild.
        The member parameter can also be an integer or User object, but the
        guild parameter must also be defined in this case.

        :param member: Member to ban
        :param guild: Guild to ban in
        :param delete_days: Number of days back to delete messages
        :param reason: Reason for banning (used in audit log)
        """
        if isinstance(member, User):
            member = member.id
        if isinstance(member, int):
            if guild is not None:
                return await self.raw_ban_member(member, guild.id,
                                                 delete_days=delete_days,
                                                 reason=reason)
            else:
                raise ValueError("Must define guild to ban a User.")

        await member.ban()

    async def raw_ban_member(self, user_id: int, guild_id: int,
                             delete_days: int = 0, reason: str = None):
        """
        Ban a user from a guild via the relevant IDs.

        :param user_id: ID of user to ban
        :param guild_id: ID of guild to ban from
        :param delete_days: Number of days back to delete messages
        :param reason: Reason for banning (used in audit log)
        """
        await self._bot.http.ban(user_id, guild_id, delete_days, reason)

    async def edit_member(self, member: Member, *, reason: str = None,
                          nick: str = NOT_SET, mute: bool = NOT_SET,
                          deafen: bool = NOT_SET,
                          voice_channel: Optional[VoiceChannel] = NOT_SET,
                          roles: List[Role] = NOT_SET):
        """
        Edit properties of a member. Any parameters that are not set will not be
        altered.

        :param member: Member to edit
        :param reason: Reason for editing (used in audit log)
        :param nick: New nickname for member
        :param mute: Boolean of whether to mute this member in voice chat
        :param deafen: Boolean of whether to deafen this member in voice chat
        :param voice_channel: Optional voice channel to move this member to
        :param roles: List of roles to replace the roles the member currently
        has
        """
        kwargs = {"reason": reason}

        for name, param in (("nick", nick), ("mute", mute), ("deafen", deafen),
                            ("voice_channel", voice_channel), ("roles", roles)):
            if param is not NOT_SET:
                kwargs[name] = param

        if len(kwargs) == 1:
            raise TypeError("No changes made in edit.")

        await member.edit(**kwargs)

    async def add_roles(self, member: Member, *roles: Role,
                        reason: str = None) -> bool:
        """
        Add new roles to a member.

        :param member: Member to add roles to
        :param roles: Roles to add
        :param reason: Reason for adding roles (used in audit log)
        :return: Boolean of whether the new set of roles is the same as the
        original
        """
        # Calculate what roles the member should have.
        # Use sets because duplicate roles causes discord to cry.
        existing = set(member.roles)
        new_roles = existing | set(roles)

        # This case normally raises, most of our use cases don't care though.
        if new_roles == existing:
            return False

        await self.edit_member(member, roles=list(new_roles), reason=reason)
        return True

    async def remove_roles(self, member: Member, *roles: Role,
                           reason: str = None) -> bool:
        """
        Remove some of a member's roles.

        :param member: Member to remove roles from
        :param roles: Roles to remove
        :param reason: Reason for removing roles (used in audit log)
        :return: Boolean indicating that the member's set of roles has actually
        changed after the command
        """
        existing = set(member.roles)
        new_roles = existing - set(roles)

        if new_roles == existing:
            return False

        await self.edit_member(member, roles=list(new_roles), reason=reason)
        return True

    async def move_member(self, member: Member, channel: Optional[VoiceChannel],
                          *, reason: str = None):
        """
        Move a member to a new voice channel. If the member is not in a voice
        channel, do nothing.

        :param member: Member to move
        :param channel: Voice channel to move member to
        :param reason: Reason for moving member (used in audit log)
        """
        if member.voice is None:
            # Cannot move a member that is not in voice already.
            return

        # If a channel is given, make sure its different to the current
        # channel, if channel is None, we know voice.channel cannot be.
        if member.voice.channel != channel:
            await self.edit_member(member, voice_channel=channel, reason=reason)

    # === Role Object =================================================

    async def edit_role(self, role: Role, *, reason: str = None,
                        name: str = NOT_SET, colour: Colour = NOT_SET,
                        hoist: bool = NOT_SET, position: int = NOT_SET,
                        permissions: Permissions = NOT_SET,
                        mentionable: bool = NOT_SET):
        """
        Edit a guild's roles. Any parameters that are not set will not be
        altered.

        :param role: Role to edit
        :param reason: Reason for editing role (used in audit log)
        :param name: New role name
        :param colour: New role name colour
        :param hoist: Boolean of whether
        :param position: New position to move the role to
        :param permissions: New set of permissions for the role
        :param mentionable: Boolean indicating the role is mentionable
        """

        kwargs = {"reason": reason}

        for name, param in (("name", name), ("mentionable", mentionable),
                            ("hoist", hoist), ("position", position),
                            ("permissions", permissions), ("colour", colour)):
            if param is not NOT_SET:
                kwargs[name] = param

        await role.edit(**kwargs)

    async def delete_role(self, role: Role, *, reason: str = None):
        """
        Delete a role from a guild.

        :param role: Role to delete
        :param reason: Reason for deleting role (used in audit logs)
        """
        await role.delete(reason=reason)

    # === Channel Object ==============================================

    async def create_invite(self, channel: Union[TextChannel, VoiceChannel], *,
                            reason: str = None, max_age: int = 0,
                            max_uses: int = 0, temporary: bool = False,
                            unique: bool = False) -> Invite:
        """
        Create an invite to a guild channel.

        :param channel: Channel to create invite to
        :param reason: Reason for creating invite (used in audit log)
        :param max_age: Amount of time before invite expires (0 for infinite)
        :param max_uses: Max amount of time the invite can be used (0 for
        invinite)
        :param temporary: Boolean indicating the member will be in temporary
        membership
        :param unique: Boolean indicating a new invite should be generated
        :return: New invite object
        """

        return await channel.create_invite(reason=reason, max_age=max_age,
                                           max_uses=max_uses, unique=unique,
                                           temporary=temporary)

    async def delete_channel(self, channel: Union[TextChannel, VoiceChannel],
                             *, reason: str = None):
        """
        Delete a guild channel.

        :param channel: Channel to delete
        :param reason: Reason for deleting channel (used in audit log)
        :return:
        """
        await channel.delete(reason=reason)

    async def invites_for(self, channel: GuildChannel) -> List[Invite]:
        """
        Retrieve a list of all invites to a channel.

        :param channel: Channel to retrieve from
        :return: List of invites to channel
        """
        return await channel.invites()

    async def edit_text_channel(self, channel: TextChannel, *,
                                reason: str = None, name: str = NOT_SET,
                                topic: str = NOT_SET, position: int = NOT_SET,
                                nsfw: bool = NOT_SET,
                                sync_permissions: bool = NOT_SET):
        """
        Edits a text channel in a guild. Any parameters not defined will not be
        altered.

        :param channel: Channel to edit
        :param reason: Reason for editing channel (used in audit log)
        :param name: New channel name
        :param topic: New channel topic
        :param position: Position to move the channel to
        :param nsfw: Boolean indicating the channel is nsfw
        :param sync_permissions: Boolean indicating to sync permissions with
        the channel's category
        """
        kwargs = {"reason": reason}
        for p_name, param in (("name", name), ("topic", topic), ("nsfw", nsfw),
                              ("position", position), ("sync_permissions",
                                                       sync_permissions)):
            if param is not NOT_SET:
                kwargs[p_name] = name

        await channel.edit(**kwargs)

    async def edit_voice_channel(self, channel: VoiceChannel, *,
                                 reason: str = None, name: str = NOT_SET,
                                 bitrate: int = NOT_SET,
                                 position: int = NOT_SET,
                                 user_limit: int = NOT_SET,
                                 sync_permissions: bool = NOT_SET):
        """
        Edits a voice channel in a guild. Any parameters not defined will not be
        altered.

        :param channel: Channel to edit
        :param reason: Reason for editing channel (used in audit log)
        :param name: New channel name
        :param bitrate: New bitrate of voice chat
        :param position: Position to move channel to
        :param user_limit: Maximum amount of users allowed in channel
        :param sync_permissions: Boolean indicating to sync permissions with the
        channel's category
        """
        kwargs = {"reason": reason}
        for p_name, param in (("name", name), ("user_limit", user_limit),
                              ("position", position), ("bitrate", bitrate),
                              ("sync_permissions", sync_permissions)):
            if param is not NOT_SET:
                kwargs[p_name] = param

        await channel.edit(**kwargs)

    @overload
    async def edit_permission_overwrites(
            self, channel: GuildChannel, target: Union[Member, Role], *,
            overwrite: PermissionOverwrite, reason: str = None): ...
    @overload
    async def edit_permission_overwrites(
            self, channel: GuildChannel, target: Union[Member, Role], *,
            reason: str = None, **permissions: bool): ...

    async def edit_permission_overwrites(self, channel: GuildChannel,
                                         target: Union[Member, Role], *,
                                         overwrite: PermissionOverwrite = None,
                                         reason: str = None,
                                         **permissions: bool):
        """
        Edit the permission overwrites of a user in a channel.

        :param channel: Channel to alter
        :param target: Member/role's permissions to edit
        :param overwrite: Permission overwrite object to use
        :param reason: Reason for editing permissions (used in audit log)
        :param permissions: Booleans for each permission
        """
        await channel.set_permissions(target, overwrite=overwrite,
                                      reason=reason, **permissions)

    async def purge_channel(self, channel: TextChannel, *, limit: int = 100,
                            check: Callable[[Message], bool] = None,
                            before: Union[Message, datetime] = None,
                            after: Union[Message, datetime] = None,
                            around: Union[Message, datetime] = None,
                            oldest_first: bool = False, bulk: bool = True
                            ) -> List[Message]:
        """
        Purge a text channel's messages and return ones that were purged.

        :param channel: Channel to purge
        :param limit: Maximum number of messages to purge
        :param check: Predicate run for each message
        :param before: Time before which each message must have been posted
        :param after: Time after which each message must have been posted
        :param around: Time around which each message must have been posted
        :param oldest_first: Boolean indicating to search through message from
        oldest to latest. By default, it will search from latest to oldest.
        :param bulk: Boolean indicating to use bulk delete
        :return: List of messages that were deleted
        """
        return await channel.purge(limit=limit, check=check, before=before,
                                   after=after, around=around,
                                   oldest_first=oldest_first, bulk=bulk)

    # =================================================================
    # === Decorators for client event handlers                      ===
    # =================================================================

    def __register_event(self, coro, name):
        """
        Registers an event function to be called for the given event.

        :param coro: Async function to run on the given event
        :param name: Name of event to run on
        """
        if not iscoroutinefunction(coro):
            raise discord.ClientException("event registered must be a "
                                          "coroutine function")
        functions = getattr(self, f"_Bot__{name}_functions")
        functions.append(coro)

        if len(functions) > 1:
            async def event_handler(*args, **kwargs):
                await gather(*[func(*args, **kwargs) for func in functions])
        elif len(functions) == 1:
            async def event_handler(*args, **kwargs):
                await functions[0](*args, **kwargs)
        else:
            raise RuntimeError("this should not ever happen")

        setattr(self._bot, name, event_handler)

    # All of the below methods are event decorators for each of discord.py's
    # events. For more info on each, see the Event Reference section in
    # discord.py's documentation.
    # There is one special decorator added for this framework, `after_command`,
    # which is run whenever a command finishes executing, whether via a command
    # error, failed auth or success.

    def on_ready(self, func: Callable[[], None]):
        self.__register_event(func, "on_ready")

    def on_error(self, func: Callable[[str, ...], Awaitable[None]]):
        self.__register_event(func, "on_error")

    def on_typing(self, func: Callable[[Messageable, User, datetime],
                                       Awaitable[None]]):
        self.__register_event(func, "on_typing")

    def on_message(self, func: Callable[[Message], Awaitable[None]]):
        # on_message is defined manually, so this needs
        # to be handled specially
        self.__on_message_functions.append(func)

    def after_command(self, func: Callable[[Context, Auth], Awaitable[None]]):
        # This isn't a real event but we're gonna pretend it is
        self.__after_command_functions.append(func)

    def on_message_delete(self, func: Callable[[Message], Awaitable[None]]):
        self.__register_event(func, "on_message_delete")

    def on_bulk_message_delete(self, func: Callable[[List[Message]],
                                                    Awaitable[None]]):
        self.__register_event(func, "on_bulk_message_delete")

    def on_raw_message_delete(
            self, func: Callable[[RawMessageDeleteEvent], Awaitable[None]]):
        self.__register_event(func, "on_raw_message_delete")

    def on_raw_bulk_message_delete(
            self, func: Callable[[RawBulkMessageDeleteEvent],
                                 Awaitable[None]]):
        self.__register_event(func, "on_raw_bulk_message_delete")

    def on_message_edit(self, func: Callable[[Message, Message],
                                             Awaitable[None]]):
        self.__register_event(func, "on_message_edit")

    def on_raw_message_edit(
            self, func: Callable[[RawMessageUpdateEvent], Awaitable[None]]):
        self.__register_event(func, "on_raw_message_edit")

    def on_reaction_add(self, func: Callable[[Reaction, User],
                                             Awaitable[None]]):
        self.__register_event(func, "on_reaction_add")

    def on_raw_reaction_add(
            self, func: Callable[[RawReactionActionEvent], Awaitable[None]]):
        self.__register_event(func, "on_raw_reaction_add")

    def on_reaction_remove(self, func: Callable[[Reaction, User],
                                                Awaitable[None]]):
        self.__register_event(func, "on_reaction_remove")

    def on_raw_reaction_remove(
            self, func: Callable[[RawReactionActionEvent], Awaitable[None]]):
        self.__register_event(func, "on_raw_reaction_remove")

    def on_reaction_clear(
            self, func: Callable[[Message, List[Reaction]], Awaitable[None]]):
        self.__register_event(func, "on_reaction_clear")

    def on_raw_reaction_clear(
            self, func: Callable[[RawReactionClearEvent], Awaitable[None]]):
        self.__register_event(func, "on_raw_reaction_clear")

    def on_guild_channel_create(
            self, func: Callable[[GuildChannel], Awaitable[None]]):
        self.__register_event(func, "on_guild_channel_create")

    def on_guild_channel_delete(
            self, func: Callable[[GuildChannel], Awaitable[None]]):
        self.__register_event(func, "on_guild_channel_delete")

    def on_guild_channel_update(
            self, func: Callable[[GuildChannel, GuildChannel],
                                 Awaitable[None]]):
        self.__register_event(func, "on_guild_channel_update")

    def on_member_join(self, func: Callable[[Member], Awaitable[None]]):
        self.__register_event(func, "on_member_join")

    def on_member_remove(self, func: Callable[[Member], Awaitable[None]]):
        self.__register_event(func, "on_member_remove")

    def on_member_update(
            self, func: Callable[[Member, Member], Awaitable[None]]):
        self.__register_event(func, "on_member_update")

    def on_user_update(self, func: Callable[[User, User], Awaitable[None]]):
        self.__register_event(func, "on_user_update")

    def on_guild_join(self, func: Callable[[Guild], Awaitable[None]]):
        self.__register_event(func, "on_guild_join")

    def on_guild_remove(self, func: Callable[[Guild], Awaitable[None]]):
        self.__register_event(func, "on_guild_remove")

    def on_guild_update(self, func: Callable[[Guild, Guild], Awaitable[None]]):
        self.__register_event(func, "on_guild_update")

    def on_guild_role_create(self, func: Callable[[Role], Awaitable[None]]):
        self.__register_event(func, "on_guild_role_create")

    def on_guild_role_delete(self, func: Callable[[Role], Awaitable[None]]):
        self.__register_event(func, "on_guild_role_delete")

    def on_guild_role_update(
            self, func: Callable[[Role, Role], Awaitable[None]]):
        self.__register_event(func, "on_guild_role_update")

    def on_guild_emojis_update(
            self, func: Callable[[Guild, List[Emoji], List[Emoji]],
                                 Awaitable[None]]):
        self.__register_event(func, "on_guild_emojis_update")

    def on_voice_state_update(
            self, func: Callable[[Member, VoiceState, VoiceState],
                                 Awaitable[None]]):
        self.__register_event(func, "on_voice_state_update")

    def on_member_ban(self, func: Callable[[Guild, User], Awaitable[None]]):
        self.__register_event(func, "on_member_ban")

    def on_member_unban(self, func: Callable[[Guild, User], Awaitable[None]]):
        self.__register_event(func, "on_member_unban")

from .command import Command
from .context import Context
from .toggle import CommandToggle

with open("config.json") as f:
    bot = Bot(json.load(f))


# noinspection PyProtectedMember
@bot._bot.event
async def on_message(message: Message):
    # noinspection PyProtectedMember,PyUnresolvedReferences
    await gather(*[func(message) for func in bot._Bot__on_message_functions])
    await bot.invoke(message)


from . import alias
from .converters import add_converter, add_manual_converter

ReactionEmoji = Union[Emoji, Reaction, PartialEmoji, str]
ReactionEmojiList = Union[str, Emoji, List[Union[str, Emoji]]]
MessageBound = Union[Message, datetime, None]
Auth = Callable[[Context], Awaitable[bool]]

