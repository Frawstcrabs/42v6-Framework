# 42v6-Framework
A discord bot framework made for 42v6, heavily inspired by the commands.ext framework in discord.py.

This framework provides a streamlined method of creating/maintaining discord commands, as well as giving fine-grained control over how commands are parsed and passed into python code.

# Features
As this framework is heavily inspired by commands.ext, many things are done in a similar way: how commands are created, the use of converters to provide modular means of converting commands into objects for use in code, the addition of per-event decorators to prevent the need to create large event functions for the entire bot, and more.

The biggest difference this framework has over commands.ext is the ability to separate the command code from the textual responses sent to the user, allowing them to be changed freely. This is used in the framework to provide multi-language support. The responses are written in an XML document and are organised by the commands they will be used by. One can also use special xml elements to add more variety to responses, such as the `<choice>` which allows a response to be picked at random from a set, `<pluralgroup>` which allows detailed control over how plurals should be conjugated in different languages, and more.

Another significant difference from commands.ext is the idea that all commands and subcommands are stored/processed in a tree structure, where all commands are treated as subcommands of a main root command. This allows processing of things like the help command or authority functions to be done much more easily.

A special exception class, CommandError, was added to give a shortcut for when a command must send an error response to the user then return from the command. This is different to the CommandError exception in commands.ext, which is a command thrown whenever a command throws its own error, and must be processed manually by the user.

Finally, the concept of converters from commands.ext was expanded upon in 42v6, allowing much finer control over how commands are processed into objects. The most significant addition was the inclusion of manual converters, which require that the converter gathers its own arguments from the command string manually and remove them from the string when processed successfully. This allows us to implement things such as Greedy[], a special converter in commands.ext, to be implemented in the same way as any other converter. A simpler form of converter, which is passed its own arg and simply returns a result, is also included, and is mostly identical to the converter type in commands.ext

# Built-in commands
As some added level of control was needed for specific parts of the framework, some default commands were added to provide control over these functions. The added commands include:
- +language, to control the language the bot speaks in depending on the channel/guild.
- +toggle, to disable commands for regular users but not bot moderators or anyone with a higher permission level.
- +alias, to allow users to change the invoker the bot uses depending on the guild it is used in. Using a mention of the bot as an invoker will always be valid, and the default invoker provided in config.json will be used otherwise. This default invoker can be disabled and new invokers added, but the mention invoker cannot be disabled.
- +help, to provide users with a means to find out how to use a command.

# How to use
The framework is a self-contained bot by itself, but requires some additional setup in order to run.

The framework uses a MySQL database to store user data, and this must be created and the credentials provided in the config file before the framework may run. If some other form of SQL database is desired, you will need to change the library and Database class in `base/database.py` to support this.

Copy the `base_config.json` file as `config.json` and update the file to include the owner's Discord account ID, the desired default invoker and the credentials to the MySQL database.

The token used to connect to Discord must be provided in an environment variable when starting, e.g. `TOKEN='your token here' python main.py`.

New commands should be added in the commands folder module, and any new files added to the `__init__.py` file to be included in the bot.

For static assets such as images, it is recommended to create a folder in the root of the framework to store them in.

Have fun.
