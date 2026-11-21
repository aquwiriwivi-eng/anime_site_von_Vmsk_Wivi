CREATE TABLE IF NOT EXISTS anime_list (
    id            SERIAL PRIMARY KEY,
    shikimori_id  VARCHAR(50)  NOT NULL UNIQUE,
    name          VARCHAR(255) NOT NULL,
    russian       VARCHAR(255),
    japanese      VARCHAR(255),
    date          DATE,
    originalurl   TEXT,
    mainurl       TEXT,
    description   TEXT
);

CREATE TABLE IF NOT EXISTS anime_of_the_week (
    id           SERIAL PRIMARY KEY,
    anime_id     INTEGER NOT NULL
                 REFERENCES anime_list(id) ON DELETE CASCADE,
    week_start   DATE NOT NULL
                 CHECK (EXTRACT(ISODOW FROM week_start) = 1),
    position     SMALLINT NOT NULL CHECK (position BETWEEN 1 AND 3),
    banner_path  TEXT NOT NULL,
    tagline      VARCHAR(40) NOT NULL
                 CHECK (char_length(tagline) BETWEEN 5 AND 40),
    is_published BOOLEAN NOT NULL DEFAULT TRUE,
    is_archived  BOOLEAN NOT NULL DEFAULT FALSE,
    archived_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Не больше 3 активных (неархивных) слотов на неделю
CREATE UNIQUE INDEX IF NOT EXISTS uq_aotw_active_slot
    ON anime_of_the_week (week_start, position)
    WHERE is_archived = FALSE;

-- Одно аниме не может занять два активных слота в одну неделю
CREATE UNIQUE INDEX IF NOT EXISTS uq_aotw_active_anime
    ON anime_of_the_week (week_start, anime_id)
    WHERE is_archived = FALSE;

CREATE INDEX IF NOT EXISTS idx_aotw_anime_id
    ON anime_of_the_week(anime_id);

CREATE INDEX IF NOT EXISTS idx_aotw_week_active
    ON anime_of_the_week(week_start, position)
    WHERE is_archived = FALSE;