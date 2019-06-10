DROP TABLE IF EXISTS invokers;
CREATE TABLE invokers (
    guild_id BIGINT UNSIGNED PRIMARY KEY,
    callstr VARCHAR(32)
);
DROP TABLE IF EXISTS guild_lang;
CREATE TABLE guild_lang (
    guild_id BIGINT UNSIGNED PRIMARY KEY,
    lang VARCHAR(15) NOT NULL
);

DROP TABLE IF EXISTS channel_lang;
CREATE TABLE channel_lang (
    channel_id BIGINT UNSIGNED PRIMARY KEY,
    lang VARCHAR(15) NOT NULL
);

DROP TABLE IF EXISTS botbans;
CREATE TABLE botbans (
    user_id BIGINT UNSIGNED NOT NULL,
    guild_id BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (user_id, guild_id)
);
CREATE INDEX botbans_guild_index ON botbans(guild_id);

DROP TABLE IF EXISTS toggles;
CREATE TABLE toggles (
    guild_id BIGINT UNSIGNED NOT NULL,
    command VARCHAR(255) NOT NULL,
    PRIMARY KEY (guild_id, command)
);

DROP PROCEDURE IF EXISTS toggle_toggle;

DELIMITER //
CREATE PROCEDURE toggle_toggle(IN guild BIGINT UNSIGNED,
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