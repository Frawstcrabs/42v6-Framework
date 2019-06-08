-- reminder that dropping a table automatically drops its indexes

CREATE TABLE IF NOT EXISTS invokers (
    guild_id BIGINT UNSIGNED NOT NULL,
    callstr VARCHAR(32)
);
CREATE INDEX IF NOT EXISTS invokers_index ON invokers(guild_id);

CREATE TABLE IF NOT EXISTS guild_lang (
    guild_id BIGINT UNSIGNED PRIMARY KEY,
    lang VARCHAR(15) NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_lang (
    channel_id BIGINT UNSIGNED PRIMARY KEY,
    lang VARCHAR(15) NOT NULL
);

CREATE TABLE IF NOT EXISTS botbans (
    user_id BIGINT UNSIGNED NOT NULL,
    guild_id BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (user_id, guild_id)
);
CREATE INDEX IF NOT EXISTS botbans_guild_index ON botbans(guild_id);

CREATE TABLE IF NOT EXISTS toggles (
    guild_id BIGINT UNSIGNED NOT NULL,
    command VARCHAR(255) NOT NULL,
    PRIMARY KEY (guild_id, command)
);

DROP PROCEDURE IF EXISTS toggle_toggle;

DELIMITER //
CREATE PROCEDURE IF NOT EXISTS toggle_toggle(IN guild BIGINT UNSIGNED,
                                             IN cmd VARCHAR(255))
BEGIN
    IF guild IS NOT NULL AND cmd IS NOT NULL THEN
        IF EXISTS (
            SELECT * FROM toggles
            WHERE guild_id = guild AND command = cmd)
        THEN
            DELETE FROM toggles
            WHERE guild_id = guild AND command = cmd;
        ELSE
            INSERT IGNORE INTO toggles  -- Thread safety
            VALUES (guild, cmd);
        END IF;
    END IF;
END //
DELIMITER ;
