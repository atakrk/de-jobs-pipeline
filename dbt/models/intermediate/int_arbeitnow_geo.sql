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

with locations as (

    select
        posting_id,
        city                              as raw_location,
        {{ norm("coalesce(city, '')") }}  as loc_norm
    from {{ ref('stg_arbeitnow__postings') }}

),

flagged as (

    select
        *,
        loc_norm ~ '\m(france|french|united kingdom|great britain|england|scotland|wales|ireland|netherlands|holland|belgium|spain|portugal|italy|poland|czech|austria|switzerland|sweden|norway|denmark|finland|greece|romania|hungary|turkey|usa|united states|canada|india|london|paris|madrid|lisbon|amsterdam|brussels|dublin|vienna|zurich|milan|warsaw|prague)\M'
            as has_foreign_marker
    from locations

),

matched as (

    select
        f.*,
        exists (
            select 1
            from {{ ref('int_german_cities') }} c
            where f.loc_norm ~ ('\m' || c.city_norm || '\M')
        ) as matches_german_place
    from flagged f

)

select
    posting_id,
    raw_location,
    has_foreign_marker,
    matches_german_place,
    case
        when has_foreign_marker   then 'FOREIGN'
        when matches_german_place then 'DEUTSCHLAND'
    end as resolved_country
from matched
