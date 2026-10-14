-- Country and city for Arbeitnow postings from the location text. Grain: (posting_id, run_date).
-- Country: FOREIGN if a foreign marker appears (wins), DEUTSCHLAND if a German place does, else null.
-- City: only when the text starts with a German place and names no other one.

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

-- Places named in the text, and whether the text starts with one.
-- A hyphen only separates with spaces ("Leinfelden-Echterdingen" is one place).
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

-- Drop places contained in a longer match ("frankfurt" in "frankfurt am main").
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
    -- max() above is only used when exactly one city was named
    case
        when not has_foreign_marker and places = 1 and begins_with_place = 1
            then city
    end as resolved_city,
    case
        when not has_foreign_marker and places = 1 and begins_with_place = 1
            then region
    end as resolved_region
from matched
