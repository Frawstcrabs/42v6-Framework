# -*- coding: utf-8 -*-

from __future__ import annotations

import random
import cachetools
from os import listdir, path
from typing import Union, Optional, Dict, List, Any, TypeVar, Callable, Tuple
from xml.etree import ElementTree as etree

from .command import Command
from .context import Context
from .database import Database as db
from .client import bot

route = "./languages/"

T = TypeVar("T")
Output = Union[str, List, Dict]


class LanguageError(Exception):
    """
    Exception raised whenever an error related to language retrieval/parsing
    occurs.
    """
    pass


class LanguageManager:
    """
    Class used to hold the XML data for each language.
    """
    data = {}
    default = "english"
    # Loading stuff

    @staticmethod
    def add_site_link(element, uri, _id_path=""):
        """
        Recursively generate 42 documentation links for a given command element
        and all of its subcommands.

        :param element: Command element
        :param uri: URI for documentation site
        :param _id_path: Optional qualification for generated url just before
        ID
        """
        id_ = element.get('id')
        element.set("site-link", f"{uri}#{_id_path}{id_}")
        for command in element.iterfind("./command"):
            LanguageManager.add_site_link(command, uri, f"{_id_path}{id_}.")

    @staticmethod
    def load_lang(folder):
        """
        Load a given language folder into memory, coalescing each of the xml
        extension files together into a single unit.

        :param folder: Path to desired language folder
        :return: Root of XML element for given language
        """
        # Get languages first
        try:
            tree = etree.parse(path.join(route, folder, "language.xml"))
            root: etree.Element = tree.getroot()
        except (etree.ParseError, OSError):
            print(f"Failed to import language \"{folder}\"")
            return None

        # Add extensions to everything
        for file in listdir(path.join(route, folder)):
            if file.endswith(".xml") and file != "language.xml":
                try:
                    tree = etree.parse(path.join(route, folder, file))
                    extension: etree.Element = tree.getroot()
                    uri = extension.attrib["site-link"]
                    command: etree.Element
                    for command in extension.iterfind("./command"):
                        LanguageManager.add_site_link(command, uri)
                        root.append(command)
                except (etree.ParseError, KeyError):
                    print(f"Failed to load extension \"{folder}/{file}\"")

        return root

    @classmethod
    def load(cls):
        """
        Load all languages found in the root language folder into memory.
        """
        for folder in listdir(route):
            if path.isdir(path.join(route, folder)):
                root = cls.load_lang(folder)
                if root is not None:
                    cls.data[root.attrib["id"]] = root

    @classmethod
    def get_object_tree(cls, lang: str):
        """
        Retrieve the root element of the given language.

        :param lang: Language ID
        :return: Root XML element of language
        """
        if lang in cls.data:
            return cls.data[lang]
        return cls.data[cls.default]

    @classmethod
    def _get_lang_or_eng(cls, element_path: str, lang: str, _ret_none=False
                         ) -> Union[etree.Element, None]:
        root = cls.get_object_tree(lang)
        element: etree.Element = root.find(element_path)
        if element is not None:
            return element

        # print(f"No data for '{element_path}' in language '{lang}'")
        root = cls.get_object_tree(cls.default)
        element = root.find(element_path)
        if element is None:
            if _ret_none:  # Simple name lol
                return None
            raise LanguageError(f"No english output value for '{element_path}'")

        return element

    @classmethod
    def get_language_element(cls, element_path: str, lang: str
                             ) -> etree.Element:
        """
        Search through a language via the given XPath to retrieve a specific
        element. If that element is not found in the given language, search the
        English language file with the same XPath. If still nothing is found,
        raise LanguageError.

        :param element_path: XPath to desired element
        :param lang: Language to initially search in
        :return: XML element
        """
        return cls._get_lang_or_eng(element_path, lang)

    # @classmethod
    # def get_language_element_list(cls, element_path: str, lang: str
    #                               ) -> List[etree.Element]:
    #     # Cant get direct parent of sub-element apparently.
    #     element = cls._get_lang_or_eng(element_path, lang, _ret_none=True)
    #     print(element, f"../{element.tag}")
    #     if element is None:
    #         return []
    #     # Find all child elements with the same tag.
    #     return list(element.iterfind(f"../{element.tag}"))

    @classmethod
    def get_language_element_list(cls, element_path: str, lang: str
                                  ) -> List[etree.Element]:
        # Try if the language works
        root = cls.get_object_tree(lang)
        element: etree.Element = root.find(element_path)
        if element is None:
            language = cls.default

        # Return list of items
        return list(root.iterfind(element_path))


# Initial load
LanguageManager.load()


def _clean_element_text(element: etree.Element, ctx: Context) -> str:
    text = element.text
    if "\n" in text:
        text = "\n".join(line.strip() for line in text.split("\n"))
    return text.strip() \
        .replace("\uF000", ctx.invoker) \
        .replace("\uF001", bot.invoker)


# - Output parsers -----------------------------------------------------

def convert_list(element: etree.Element, **kwargs: Any
                 ) -> List[Output]:
    """
    Convert a <list> element into a list object of all of its children.
    Each of its children is also parsed.

    :param element: <list> element to parse
    :param kwargs: Kwargs passed for sub-elements
    :return: List object of parsed output elements
    """
    output = []
    for child in list(element):
        output.append(convert(child, **kwargs))
    return output


def convert_dict(element: etree.Element, **kwargs: Any
                 ) -> Dict[str, Output]:
    """
    Convert a <dict> element into a dict object, where the name attribute of
    each <entry> element is used as the key, and the child of that entry the
    value of that key. Each entry is also parsed as an output element.

    :param element: <dict> element to parse
    :param kwargs: Kwargs passed for sub-elements
    :return: Dict object containing all entries
    """
    output = {}
    for child in list(element):
        key = child.get("name")
        value = convert(child[0], **kwargs)
        output[key] = value
    return output


def _weight_choice(items: List[T], weights: List[Union[float, int]]) -> T:
    assert len(items) == len(weights)
    prob = sum(weights)
    chosen = random.uniform(0, prob)
    total = 0
    for item, weight in zip(items, weights):
        total += weight
        if chosen < total:
            return item

    raise RuntimeError("Invalid weights set")


def convert_choice(element: etree.Element, **kwargs: Any) -> str:
    """
    Convert a <choice> by randomly choose one of its child elements. For
    weighted randomness, each of the entries must have a weight attribute as a
    float from 0 to 1.

    :param element: <choice> element to convert
    :return: Random child element
    """
    lines = []
    weights = []
    use_weights = False
    for child in list(element):
        w = element.get("weight")
        if w is not None:
            use_weights = True
            weights.append(w)
        lines.append(child)

    if use_weights:
        try:
            return _weight_choice(lines, weights)
        except AssertionError:
            raise ValueError("Either all or no choices must have a weight")

    return _clean_element_text(random.choice(lines), kwargs["ctx"])


def convert_plural(element: etree.Element, *, numerical_ref: int, **kwargs: Any
                   ) -> str:
    """
    Convert a <pluralgroup> element into one of its children, using the
    numerical_ref parameter to select. Each child is iterated in order of
    declaration, checking if the value attribute matches the numerical
    ref exactly, or if the numerical ref is in between the lower and upper
    attributes if defined. The special value "default" can be used as a fallback
    string.

    :param element: <pluralgroup> element to convert
    :param numerical_ref: Number to use when finding correct plural entry
    :return: Response line with correct plural value
    """
    for elem in element.iterfind("./plural"):
        value = elem.get("value")
        check = (
            value not in [None, ""] and (
                value == "default" or
                numerical_ref == float(value)
            )
        )
        if check:
            return _clean_element_text(elem, kwargs["ctx"])

        lower = elem.get("lower")
        upper = elem.get("upper")
        if lower in [None, ""] or numerical_ref < float(lower):
            continue
        if upper in [None, ""] or numerical_ref > float(upper):
            continue

        return _clean_element_text(elem, kwargs["ctx"])

    raise ValueError(f"Pluralgroup contains no value for {numerical_ref}")


def convert(element: etree.Element, **kwargs: Any) -> Output:
    """
    Convert a given output element into its correct value. The supported
    output elements are <line>, <list>, <dict>, <choice>, <pluralgroup>
    and <nonetype>.

    This will also replace any placeholders for the global invoker/user invoker
    with their actual values.

    :param element: Output element to convert
    :param kwargs: Kwargs used depending on type of element passed
    :return: Output value
    """
    switch = {
        "line": lambda e, **kw: _clean_element_text(e, kw["ctx"]),
        "list": convert_list,
        "dict": convert_dict,
        "choice": convert_choice,
        "pluralgroup": convert_plural,
        "nonetype": lambda _, **__: None
    }

    return switch[element.tag](element, **kwargs)


def get_output(command: Command, element: str, ctx: Context,
               *, numerical_ref: int = None) -> Output:
    """
    Search for an output value from the output space of a command and the
    value's ID.

    :param command: Command object to use as a namespace
    :param element: Output ID
    :param ctx: Command context
    :param numerical_ref: Numerical ref used to convert <pluralgroup> values
    :return: Output value
    """
    element_path: str = command.path
    element_path += f"/output/*[@id='{element}']"

    element = LanguageManager.get_language_element(element_path, ctx.lang)

    return convert(element, ctx=ctx, numerical_ref=numerical_ref)


def get_output_recursive(element_path: Command, element: str, ctx: Context,
                         *, numerical_ref: int = None) -> Output:
    """
    Search for an output value from the output space of a command and the
    value's ID. If the value is not found, recurse into the parent output space
    and search again. If no value at all is found, raise LanguageError.

    :param element_path: Command object to use as a namespace
    :param element: Output ID
    :param ctx: Command context
    :param numerical_ref: Numerical ref used to convert <pluralgroup> values
    :return: Output value
    """
    curr_element: Optional[Command] = element_path

    while curr_element is not None:
        try:
            return get_output(curr_element, element, ctx,
                              numerical_ref=numerical_ref)
        except LanguageError:
            curr_element = curr_element.parent

    raise LanguageError("No output in tree from root to "
                        f"{element_path.path} for {element}")


def get_coalesce(element_path: Command, elements: List[str], ctx: Context,
                 *, numerical_ref: int = None):
    """
    Search for the first value in the elements parameter in the output space in
    the given command, recursing into the parent output space if not found. If
    no value is found, try again with the next value of elements, repeating for
    each value. If no value is found, raise LanguageError.

    :param element_path: Command object to use as a namespace
    :param elements: Output IDs
    :param ctx: Command context
    :param numerical_ref: Numerical ref used to convert <pluralgroup> values
    :return: Output value
    """
    for element in elements:
        try:
            return get_output_recursive(element_path, element, ctx,
                                        numerical_ref=numerical_ref)
        except LanguageError:
            pass

    raise LanguageError("No output in tree from root to "
                        f"{element_path.path} for elements {elements}")


# - Help parsers -------------------------------------------------------

def get_command_qualified_name(command: Command, ctx: Context) -> str:
    """
    Retrieve the full name of a command, consisting of the names of all of its
    ancestor commands separated by spaces and starting from the topmost command.
    This command will retrieve

    :param command: Command object to retrieve name of
    :param ctx: Command context
    :return: Full command name
    """
    output = []
    while command.parent is not None:  # Cut off before processing root
        element = LanguageManager.get_language_element(command.path, ctx.lang)
        output.append(element.get("name"))
        command = command.parent

    return " ".join(reversed(output))


def get_command_description(command: Command, ctx: Context) -> str:
    """
    Retrieve the description of a command. This will also replace the
    placeholders for the global invoker/user invoker with their actual values.

    :param command: Command to retrieve from
    :param ctx: Command context
    :return: Description string
    """
    element_path: str = command.path + f"/description"
    element = LanguageManager.get_language_element(element_path, ctx.lang)
    return _clean_element_text(element, ctx)


def get_command_help_lines(command: Command, ctx: Context
                           ) -> List[Tuple[str, str]]:
    """
    Retrieve the list of all example command usages, along with each explanation
    of what it does.

    :param command: Command to retrieve from
    :param ctx: Command context
    :return: List of tuples containing the example command usage and the
    associated explanation string
    """
    element_path: str = command.path + "/helpsection"
    elements = LanguageManager.get_language_element_list(element_path,
                                                         ctx.lang)

    # Coerce elements into nice lines
    output = []
    qual_name = get_command_qualified_name(command, ctx)

    for element in elements:
        args = element.get("args", "")
        cmd = f"{ctx.invoker}{qual_name} {args}"
        output.append((cmd, _clean_element_text(element, ctx)))

    return output


def get_command_parent_help(command: Command, ctx: Context
                            ) -> Optional[Tuple[str, str]]:
    """
    Retrieve the help section to be used in the given command's parent's help
    section.

    :param command: Command to retrieve from
    :param ctx: Command context
    :return: Help section for parent of command
    """
    element_path = command.path + "/parenthelpsection"
    element = LanguageManager.get_language_element(element_path, ctx.lang)

    if element is not None:
        qual_name = get_command_qualified_name(command, ctx)
        args = element.get("args", "")
        cmd = f"{ctx.invoker}{qual_name} {args}"
        return cmd, _clean_element_text(element, ctx)

    return None


def get_command_link(command: Command, ctx: Context) -> str:
    """
    Retrieve the link to the website's documentation of this command.

    :param command: Command to retrieve from
    :param ctx: Command context
    :return: Link to website documentation
    """
    element = LanguageManager.get_language_element(command.path, ctx.lang)
    return element.get("site-link")


def get_language_names():
    """
    Retrieve a list of all available language names.

    :return: List of language names
    """
    ret = {}
    for lang, root in LanguageManager.data.items():
        name = root.attrib["name"]
        if name is None:
            ret[lang] = lang
        else:
            ret[lang] = name
    return ret


# - Command Aliases ----------------------------------------------------

def get_command_names(command: Command) -> List[str]:
    """
    Retrieve a list of all possible names by which a command may be referred to
    in a command string. Each name is a string containing the language for which
    the name belongs and the name itself, separated with a space.

    :param command: Command to search for
    :return: List of all qualified command names
    """
    output = [command.id, command.id + "_"]
    # Underscore to access ID if command is shadowed by language.
    for language in LanguageManager.data:
        element = LanguageManager.get_language_element(command.path, language)
        names = [element.get("name")]
        alias = element.get("alias")
        if alias is not None:
            names.extend(alias.split())

        output.extend(f"{language} {key}" for key in names)

    return output


_guild_cache = cachetools.LFUCache(100)
_channel_cache = cachetools.LFUCache(500)


async def get_lang(guild_id, channel_id):
    """
    Retrieve the language for a channel, taking into account channel overrides.

    :param guild_id: Guild ID
    :param channel_id: Channel ID
    :return: Language name
    """
    try:
        channel_lang = _channel_cache[channel_id]
    except KeyError:
        channel_lang = await db.fetchone("""
            SELECT lang FROM channel_lang
            WHERE channel_id = %s;
        """, channel_id)
        _channel_cache[channel_id] = channel_lang

    if channel_lang is not None:
        return channel_lang

    # channel id not found, check guild
    try:
        if guild_id is None:
            guild_lang = None
        else:
            guild_lang = _guild_cache[guild_id]
    except KeyError:
        guild_lang = await db.fetchone("""
            SELECT lang FROM guild_lang
            WHERE guild_id = %s;
        """, guild_id)
        _guild_cache[guild_id] = guild_lang

    if guild_lang is not None:
        return guild_lang

    return LanguageManager.default


async def set_guild_lang(guild_id, lang):
    """
    Set the language for a guild.

    :param guild_id: Guild ID
    :param lang: New language string
    """
    _guild_cache[guild_id] = lang
    await db.execute("""
        INSERT INTO guild_lang
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE 
            lang = %s;
    """, guild_id, lang, lang)


async def set_channel_lang(channel_id, lang):
    """
    Set the language for a channel.

    :param channel_id: Channel ID
    :param lang: New language string
    """
    # need to test if lang matches the guild lang
    _channel_cache[channel_id] = lang
    await db.execute("""
        INSERT INTO channel_lang
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE 
            lang = %s;
    """, channel_id, lang, lang)
