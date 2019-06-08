# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Union, Awaitable

from discord import Embed, Emoji, RawReactionActionEvent, PartialEmoji, Message

from . import Context


class ButtonController(ABC):
    """A basic button controller."""

    __slots__ = ["ctx", "buttons", "timeout", "message", "_initialise"]

    def __init__(self, ctx: Context,
                 initialise: Awaitable[Message],
                 buttons: List[str, Emoji],
                 timeout: int = 30):
        """Defines a new button controller

        :param ctx: The Context which defines the channel and owner
        :param initialise: An awaitable that posts the initial message
        :param buttons:
            A list of unicode emoji or discord.Emoji to use as buttons
        :param timeout:
            Time in seconds before the controller automatically closes
        """
        self.ctx = ctx
        self._initialise = initialise
        self.buttons = buttons
        self.timeout = timeout
        self.message = None

    @abstractmethod
    async def on_button_press(self, button: Union[str, Emoji]):
        """Event to run when one of the buttons is pressed

        For a button to prematurely close the embed, it should raise
        StopAsyncIteration, at which point the buttons will automatically
        be cleared and execution will return to the calling thread.

        :param button: the button that was pressed.
        """
        return NotImplemented

    async def _close(self):
        await self.ctx.bot.clear_reactions(self.message)
        del self.message

    async def _wait_for_button(self) -> Union[str, int, None]:
        payload: RawReactionActionEvent = await self.ctx.bot.wait_for_reaction(
                self.buttons, user=self.ctx.author, message=self.message,
                timeout=self.timeout)

        if payload is None:
            return None

        # payload.emoji is a PartialEmoji
        emoji: PartialEmoji = payload.emoji

        # User and Member implement Snowflake
        # noinspection PyTypeChecker
        await self.ctx.bot.remove_reaction(self.message, emoji,
                                           self.ctx.author)

        if emoji.is_unicode_emoji():
            return emoji.name

        # payload.emoji.id returns int if emoji is custom emoji, None otherwise
        # noinspection PyTypeChecker
        return emoji.id

    async def start(self):
        """Starts the controller.

        This call holds control until the controller is completed and returns
        """
        self.message = await self._initialise

        for button in self.buttons:
            await self.ctx.bot.add_reaction(self.message, button)

        try:
            while True:
                button = await self._wait_for_button()
                if not button:
                    break
                await self.on_button_press(button)
        except StopAsyncIteration:
            pass

        await self._close()


class BasePager(ButtonController):
    """A subclassable pager object

    You can define some class variables to change how the embed works and
    will be displayed.

    :var PREV: The unicode emoji for going back one page
    :var PREV_FEW: The unicode emoji for going back "few" pages
    :var PREV_MANY: The unicode emoji for going back "many" pages
    :var NEXT: The unicode emoji for going forward one page
    :var NEXT_FEW: The unicode emoji for going forward "few" pages
    :var NEXT_MANY: The unicode emoji for going forward "many" pages
    :var CLOSE: The unicode emoji for closing the pager
    :var FEW_STEP: The number of pages that the "few" button will jump
    :var MANY_STEP: The number of pages that the "many" button will jump
    """
    __slots__ = ["pages", "pointer"]

    PREV = "\u2b05"
    PREV_FEW = "\u23ea"
    PREV_MANY = "\u23ee"
    NEXT = "\u27a1"
    NEXT_FEW = "\u23e9"
    NEXT_MANY = "\u23ed"
    CLOSE = "\U0001f1fd"

    FEW_STEP = 5
    MANY_STEP = 20

    def __init__(self, ctx: Context, *pages: Embed, timeout: int =30,
                 extra_buttons: List[str, Emoji] = None):
        """A simple pagination object

        This defines a simple pager with reactive next and previous page
        buttons for navigation.

        This can be subclassed to add additional functionality.

        :param ctx: The Context defining the owner and channel of the pager
        :param pages:
            A set of discord.Embed objects which should be in the same page
            order. Page numbers will be automatically appended to the footer.
        :param timeout: How long before the pager automatically closes.
        :param extra_buttons: A list of additional buttons to apply.
        """
        self.ctx = ctx
        self.pages: List[Embed] = self.make_pages(*pages)
        self.pointer = 0

        try:
            init = ctx.post(embed=self.pages[0])
        except IndexError:
            raise TypeError("At least one page must be specified") from None

        buttons = [self.PREV, self.NEXT]

        if len(pages) > self.FEW_STEP:
            buttons.insert(0, self.PREV_FEW)
            buttons.append(self.NEXT_FEW)

        if len(pages) > self.MANY_STEP:
            buttons.insert(0, self.PREV_MANY)
            buttons.append(self.NEXT_MANY)

        if extra_buttons:
            buttons.extend(extra_buttons)

        buttons.append(self.CLOSE)

        ButtonController.__init__(self, ctx, init, buttons, timeout)

    def make_pages(self, *pages: Embed) -> List[Embed]:
        """Formats a list of Embeds

        This adds the page (language accurate) page numbers to the embed
        footers. This can be overridden to change how the embeds are
        formatted.

        :param pages: The list of Embeds to format
        :return: The list of formatted Embeds
        """
        line = self.ctx.get_raw_output("paginator_footer")
        pages = list(pages)
        total = len(pages)
        for idx, page in enumerate(pages):
            page.set_footer(text=line.format(idx + 1, total))
        return pages

    async def close(self):
        """Closes the pager

        By default, this will edit the message into a language dependant
        "paginator closed" message, but this can be overridden to change
        what happens when the pager is closed.
        """
        msg = self.ctx.get_output("paginator_closed")
        embed = Embed(description=msg, colour=0)
        await self.ctx.edit(embed=embed)

    async def on_button_press(self, button: Union[str, Emoji]):
        """Handles when a button is pressed

        This handles the page change buttons and close button. If this method
        is overridden, ensure that super().on_button_pressed is called too.

        :param button: The button that was pressed
        """
        # Test close
        if button == self.CLOSE:
            await self.close()
            raise StopAsyncIteration()

        # Set up callbacks
        callbacks = {
            self.NEXT: lambda s: (s.pointer + 1) % len(s.pages),
            self.PREV: lambda s: (s.pointer - 1) % len(s.pages),
            self.NEXT_FEW: lambda s: (s.pointer + s.FEW_STEP) % len(s.pages),
            self.PREV_FEW: lambda s: (s.pointer - s.FEW_STEP) % len(s.pages),
            self.NEXT_MANY: lambda s: (s.pointer + s.MANY_STEP) % len(s.pages),
            self.PREV_MANY: lambda s: (s.pointer - s.MANY_STEP) % len(s.pages)
        }

        self.pointer = callbacks[button](self)
        await self.ctx.edit(embed=self.pages[self.pointer])

    async def start(self):
        """Starts the pager."""
        if len(self.pages) == 1:
            await self._initialise
            return

        await ButtonController.start(self)


class Icon:
    class Type(Enum):
        BOOKMARK = 0
        CLOCK = 1
        CROSS = 2
        DIAMOND = 3
        DOWN_ARROW = 4
        FOUR_TWO = 5
        HEART = 6
        LARGE_SQUARE = 7
        LIST = 8
        POINTER = 9
        RING = 10
        SERVER = 11
        SETTINGS = 12
        SMALL_SQUARE = 13
        SMILE = 14
        STATS = 15
        TARGET = 16
        THINK = 17
        UP_ARROW = 18
        INFORMATION = 19

    class Colour(Enum):
        RED = 0
        ORANGE = 1
        YELLOW = 2
        GREEN = 3
        CYAN = 4
        BLUE = 5
        INDIGO = 6
        PURPLE = 7
        PINK = 8
        BLACK = 9

    with open("files/emotes.json") as file:
        _ids: List[List[int]] = json.load(file)

    @classmethod
    def get_id(cls, type_: Type, colour: Colour) -> int:
        """Gets the ID of an emote

        :param type_: The emote shape
        :param colour: The emote colour
        :return: The emote's ID
        """
        return cls._ids[type_.value()][colour.value()]

    @classmethod
    def get_emote(cls, type_: Type, colour: Colour) -> str:
        """Gets a discord formatted version of an emote

        :param type_: The emote shape
        :param colour: The emote colour
        :return: A formatted (enough) string to post as an emote
        """
        return f"<:_:{cls.get_id(type_, colour)}>"

    @classmethod
    def get_colour(cls, colour: Colour) -> int:
        """Gets the hex value of a colour

        :param colour: The emote colour
        :return: The colour's real value
        """
        return [
            0xE01C1C, 0xE0861C, 0xEAF12D, 0x89F12D, 0x2FF1C6,
            0x23B8FD, 0x8966FB, 0xCC66FB, 0xFB7ADB, 0x7F7F7F
        ][colour.value()]


class NamedPage:
    __slots__ = ("embed", "name", "icon")

    def __init__(self, embed: Embed, name: str,
                 icon: Icon.Type = Icon.Type.SMALL_SQUARE):
        """A named page for the NamedPager

        The icon colour will be automatically set.

        :param embed: The embed to use as the page
        :param name: The name of the page
        :param icon: The icon shape.
        """
        self.embed = embed
        self.name = name
        self.icon = icon


class NamedPager(BasePager):

    FEW_STEP = 11  # Ensure this button is never added

    def __init__(self, ctx: Context, *pages: NamedPage):
        """Creates a new pager from named pages.

        :param ctx: The Context defining the owner and channel
        :param pages:
            Up to 9 ordered NamedPages. Colours are set automatically
        """
        if len(pages) > 9:
            raise RuntimeError("Can only handle 9 pages at once.")
        BasePager.__init__(self, ctx, *pages)

    def make_pages(self, *pages: NamedPage) -> List[Embed]:
        pages: List[NamedPage] = list(pages)

        # First draw the icon row
        icons = []

        for idx, page in enumerate(pages):
            icons.append(Icon.get_emote(page.icon, Icon.Colour(idx)))

        # Add to each page
        title = self.ctx.get_output("paginator_paging_title")
        for idx, page in enumerate(pages):
            footer = icons.copy()
            footer[idx] = (Icon.get_emote(Icon.Type.POINTER, Icon.Colour(idx))
                           + page.name)
            page.embed.add_field(name=title, value="".join(footer),
                                 inline=False)
            page.embed.colour = Icon.get_colour(Icon.Colour(idx))

        return [page.embed for page in pages]


class Lister(BasePager):

    def __init__(self, ctx: Context, *items: str, rows: int = 10,
                 cols: int = 2, **embed_args):
        """Reads a list of strings into a pager.

        Note that each column can only support 1024 characters.
        The number of columns shouldn't *really* exceed 3.

        :param ctx: The Context defining the owner and channel
        :param items: The items to list in the pager
        :param rows: The number of rows
        :param cols: The number of columns
        :param embed_args:
            Keyword arguments that are passed into the constructor for Embed
        """
        # Convert items into embeds.
        # Sort elements first? Nah, the caller can sort
        chunks = [items[idx:idx+rows] for idx in range(0, len(items), rows)]

        embeds = []
        pages = [chunks[idx:idx+cols] for idx in range(0, len(chunks), cols)]

        for page in pages:
            embed = Embed(**embed_args)
            for list_ in page:
                embed.add_field(name="\u200b", value="\n".join(list_))
            embeds.append(embed)

        BasePager.__init__(self, ctx, *embeds)
