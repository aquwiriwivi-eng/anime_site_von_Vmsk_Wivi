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