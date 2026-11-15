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
                 CHECK (char_length(tagline) BETWEEN 5 AND 30),
    is_published BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (week_start, position),   -- не больше 3 слотов на неделю
    UNIQUE (week_start, anime_id)    -- одно аниме не может занять два слота в одну неделю
);

CREATE INDEX IF NOT EXISTS idx_aotw_anime_id ON anime_of_the_week(anime_id);