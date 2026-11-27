-- ===========================================================================
--  AEGIS · esquema PostGIS para series temporales de inteligencia
--  Aplicado automáticamente por app/storage/postgis.py al arrancar.
--
--  Diseño:
--    * `events` está PARTICIONADA POR RANGO MENSUAL sobre event_time
--      -> un DELETE de retención es un DROP PARTITION (instantáneo), y las
--         consultas por ventana temporal hacen partition pruning.
--    * Índice GiST sobre la geografía: bbox (&&) y radio (ST_DWithin).
--    * Índice BRIN sobre event_time dentro de cada partición: ocupa ~kB por
--      partición frente a MB de un B-Tree, ideal para append-only temporal.
--    * B-Tree (category, event_time DESC) para los filtros de capa del mapa.
--    * GIN sobre payload para búsquedas en metadatos CAMEO.
--
--  Regla de oro de proximidad (NO negociable):
--      SELECT ... WHERE ST_DWithin(geom, punto, metros)     -- usa GiST
--      -- nunca ST_Buffer(geom, r) && ST_Intersects(...)    -- seq scan
-- ===========================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS btree_gin;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------------------
-- Helper: crea las particiones mensuales que falten (mes actual ± N)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ensure_event_partitions(months_back int DEFAULT 2,
                                                   months_fwd  int DEFAULT 3)
RETURNS void AS $$
DECLARE
    m date;
BEGIN
    FOR i IN -months_back..months_fwd LOOP
        m := date_trunc('month', now())::date + (i || ' month')::interval;
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS events_%s PARTITION OF events
               FOR VALUES FROM (%L) TO (%L)',
            to_char(m, 'YYYYMM'), m, m + interval '1 month');
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS events_%s_time_brin ON events_%s USING brin (event_time)',
            to_char(m, 'YYYYMM'), to_char(m, 'YYYYMM'));
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- Eventos consolidados (una fila = un suceso, N menciones)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    id              text        NOT NULL,
    cluster_id      text        NOT NULL,
    source          text        NOT NULL,
    sources         text[]      NOT NULL DEFAULT ARRAY[]::text[],
    category        text        NOT NULL,
    subtype         text        DEFAULT '',
    title           text        NOT NULL,
    summary         text        DEFAULT '',
    lat             double precision NOT NULL,
    lon             double precision NOT NULL,
    geom            geography(Point, 4326) NOT NULL,
    depth_km        double precision,
    severity        double precision,
    severity_label  text        DEFAULT '',
    country         text        DEFAULT '',
    iso3            text        DEFAULT '',
    event_time      timestamptz NOT NULL,
    first_seen      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    url             text        DEFAULT '',
    mentions        integer     NOT NULL DEFAULT 1,
    sources_count   integer     NOT NULL DEFAULT 1,
    confidence      real        NOT NULL DEFAULT 0.45,
    payload         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    geometry_json   text,
    embedding       real[],
    PRIMARY KEY (id, event_time)
) PARTITION BY RANGE (event_time);

-- partición por defecto: nunca falla un INSERT por una fecha inesperada
CREATE TABLE IF NOT EXISTS events_default PARTITION OF events DEFAULT;

CREATE INDEX IF NOT EXISTS events_geom_gist   ON events USING gist (geom);
CREATE INDEX IF NOT EXISTS events_cat_time    ON events (category, event_time DESC);
CREATE INDEX IF NOT EXISTS events_cluster_idx ON events (cluster_id);
CREATE INDEX IF NOT EXISTS events_sev_idx     ON events (severity_label, event_time DESC);
CREATE INDEX IF NOT EXISTS events_payload_gin ON events USING gin (payload jsonb_path_ops);
CREATE INDEX IF NOT EXISTS events_title_trgm  ON events USING gin (title gin_trgm_ops);

SELECT ensure_event_partitions();

-- ---------------------------------------------------------------------------
-- Menciones: la cola de corroboración del pipeline de deduplicación
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS event_mentions (
    id        bigserial PRIMARY KEY,
    event_id  text        NOT NULL,
    source    text        NOT NULL,
    title     text,
    url       text,
    seen_at   timestamptz NOT NULL DEFAULT now(),
    score     real,
    payload   jsonb       NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS mentions_event_idx ON event_mentions (event_id, seen_at DESC);
CREATE INDEX IF NOT EXISTS mentions_seen_brin ON event_mentions USING brin (seen_at);

-- ---------------------------------------------------------------------------
-- Infraestructura: el universo de las consultas ST_DWithin
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS infrastructure (
    id         text PRIMARY KEY,
    name       text NOT NULL,
    kind       text NOT NULL,          -- city | port | airport | power | hospital ...
    subtype    text DEFAULT '',
    country    text DEFAULT '',
    iso3       text DEFAULT '',
    lat        double precision NOT NULL,
    lon        double precision NOT NULL,
    geom       geography(Point, 4326) NOT NULL,
    population double precision DEFAULT 0,
    metadata   jsonb DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS infra_geom_gist ON infrastructure USING gist (geom);
CREATE INDEX IF NOT EXISTS infra_kind_idx  ON infrastructure (kind, country);

-- ---------------------------------------------------------------------------
-- Observabilidad de la ingesta
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingest_runs (
    id          bigserial PRIMARY KEY,
    source      text NOT NULL,
    started_at  timestamptz NOT NULL DEFAULT now(),
    ok          boolean NOT NULL,
    items       integer NOT NULL DEFAULT 0,
    message     text DEFAULT '',
    duration_ms integer NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS runs_started_brin ON ingest_runs USING brin (started_at);

-- ---------------------------------------------------------------------------
-- Geovallas (espejo de Tile38: el motor vive en Tile38, aquí la definición)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fences (
    id            text PRIMARY KEY,
    name          text NOT NULL,
    kind          text NOT NULL DEFAULT 'circle',
    lat           double precision,
    lon           double precision,
    radius_m      double precision,
    geometry_json text,
    rules         jsonb NOT NULL DEFAULT '[]'::jsonb,
    active        boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Alertas push disparadas por FENCE / DETECT
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id         bigserial PRIMARY KEY,
    ts         timestamptz NOT NULL DEFAULT now(),
    fence_id   text,
    actor_id   text,
    actor_type text,
    event_type text,          -- enter | exit | inside | rule
    severity   text,
    title      text,
    message    text,
    lat        double precision,
    lon        double precision,
    payload    jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS alerts_ts_brin ON alerts USING brin (ts);
CREATE INDEX IF NOT EXISTS alerts_fence_idx ON alerts (fence_id, ts DESC);

-- ---------------------------------------------------------------------------
-- Vistas de apoyo (opcionales, consumidas por analítica externa)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW events_recent AS
    SELECT id, category, severity_label, severity, lat, lon, event_time,
           mentions, sources_count, confidence, title
    FROM events
    WHERE event_time > now() - interval '48 hours';

CREATE OR REPLACE VIEW clustering_quality AS
    SELECT category,
           count(*)                                        AS consolidated_events,
           sum(mentions)                                   AS total_mentions,
           round(avg(mentions)::numeric, 2)                AS mentions_per_event,
           round(avg(sources_count)::numeric, 2)           AS sources_per_event,
           count(*) FILTER (WHERE sources_count > 1)       AS multi_source
    FROM events
    GROUP BY category
    ORDER BY total_mentions DESC;
