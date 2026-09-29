-- Resolve a country for the second source, which never states one.
--
-- Three outcomes, and the third is deliberate:
--   DEUTSCHLAND - a known German place name appears in the location text
--   FOREIGN     - an explicit non-German country or capital appears
--   null        - "Remote", "Europe - Remote", or empty: genuinely unknown
--
-- An explicit foreign marker beats a city match, so "Frankfurt, USA" would
-- not slip through on the strength of the word Frankfurt.
--
-- Unknown stays unknown rather than being assumed German. Assuming is what
-- put London and Paris inside figures reported as the German market.
--
-- It also names the city, where one city can be named. Until it did, the
-- second source's location text went into the city table verbatim: Berlin
-- appeared six times -- "Berlin", "Berlin, Germany", "Berlin, Berlin,
-- Deutschland" and so on -- and "Munich" sat beside München as a separate
-- city. The rule is narrower than the country rule, on purpose. A posting
-- gets a city only when
--
--   - its location text begins with a known German place, and
--   - no other known place appears anywhere in it.
--
-- Anywhere-in-the-text was measured first and rejected. It resolved
-- "Mainz oder Berlin" and "Frankfurt/Düsseldorf" to one city each -- the one
-- the place list happened to know -- and "Achim (bei Bremen)" and "Garching b.
-- München" to cities they are not in. The place list is only as complete as
-- the federal postings that built it, so one match anywhere is not evidence
-- of one city. A match where the text starts is. "Berlin; Munich; Remote" is
-- several cities and gets none: publishing it under whichever came first
-- would be a choice the source never made.
--
-- Over every run in the warehouse on 2026-09-29, 2,783 of 3,000 German
-- posting-runs resolve. The other 217 -- "Hamburg, München, Düsseldorf,
-- remote", "Berlin; Munich", and text like "Berlin Office" or "Hybrid/München"
-- that does not begin with the place -- keep a null city and are counted as
-- Unknown in the city table rather than guessed. Some of those are plainly
-- Berlin to a reader. The rule gives them up so that nothing it keeps is a
-- guess.
--
-- Grain is (posting_id, run_date), the same as the staging model it reads.
-- A board posting reappears every morning it is still listed, and its location
-- text can change between them, so resolving per run rather than per posting
-- is both correct and the only grain that joins cleanly downstream.

with german_places as (

    select city_norm, city, region from {{ ref('int_german_cities') }}

),

locations as (

    select
        posting_id,
        run_date,
        city                              as raw_location,
        {{ norm("coalesce(city, '')") }}  as loc_norm
    from {{ ref('stg_arbeitnow__postings') }}

),

flagged as (

    select
        *,
        {{ imatch_word('loc_norm', 'france|french|united kingdom|great britain|england|scotland|wales|ireland|netherlands|holland|belgium|spain|portugal|italy|poland|czech|austria|switzerland|sweden|norway|denmark|finland|greece|romania|hungary|turkey|usa|united states|canada|india|london|paris|madrid|lisbon|amsterdam|brussels|dublin|vienna|zurich|milan|warsaw|prague') }}
            as has_foreign_marker
    from locations

),

-- Every known place named anywhere in the location text, and whether the
-- text begins with it: the place, then optional spaces, then the end or a
-- separator. A hyphen separates only with spaces round it, because
-- "Leinfelden-Echterdingen" is one place.
place_matches as (

    select
        f.posting_id,
        f.run_date,
        c.city_norm,
        c.city,
        c.region,
        {{ match_expr('f.loc_norm', "concat('^ *', c.city_norm, ' *($|[,;/|(]| - )')") }}
            as is_leading
    from flagged f
    join german_places c
        on {{ match_word_expr('f.loc_norm', 'c.city_norm') }}

),

-- A place named only as part of a longer one is not a second place:
-- "frankfurt am main" contains "frankfurt", and that is one city.
distinct_places as (

    select m.*
    from place_matches m
    where not exists (
        select 1
        from place_matches o
        where o.posting_id = m.posting_id
          and o.run_date = m.run_date
          and o.city_norm <> m.city_norm
          and {{ match_word_expr('o.city_norm', 'm.city_norm') }}
    )

),

-- Counted by the name it publishes under, so "Munich, München" is one city.
places_named as (

    select
        posting_id,
        run_date,
        count(distinct city)                         as places,
        max(case when is_leading then 1 else 0 end)  as begins_with_place,
        max(city)                                    as city,
        max(region)                                  as region
    from distinct_places
    group by posting_id, run_date

),

matched as (

    select
        f.*,
        p.posting_id is not null as matches_german_place,
        p.places,
        p.begins_with_place,
        p.city,
        p.region
    from flagged f
    left join places_named p
        on p.posting_id = f.posting_id
       and p.run_date = f.run_date

)

select
    posting_id,
    run_date,
    raw_location,
    has_foreign_marker,
    matches_german_place,
    case
        when has_foreign_marker   then 'FOREIGN'
        when matches_german_place then 'DEUTSCHLAND'
    end as resolved_country,
    -- max() above is only read when exactly one city was named, so it picks
    -- nothing; it is how an aggregate returns the one value there is.
    case
        when not has_foreign_marker and places = 1 and begins_with_place = 1
            then city
    end as resolved_city,
    case
        when not has_foreign_marker and places = 1 and begins_with_place = 1
            then region
    end as resolved_region
from matched
