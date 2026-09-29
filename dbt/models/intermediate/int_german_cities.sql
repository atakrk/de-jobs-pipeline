-- A reference list of German place names, derived from the federal database.
--
-- The second source states no country, only free-text location, so something
-- has to decide whether "Dusseldorf" and "Manchester" belong in a dataset
-- about Germany. Rather than hand-maintain a list or call a geocoder, we use
-- the place names the federal job database itself reports -- tens of
-- thousands of postings across the country. The dataset validates itself.
--
-- Only places the federal source itself puts in Germany. It also lists
-- Austrian vacancies, and for a while their towns were on this list too --
-- Linz, Wels, Wiener Neudorf, a place called "Österreich" -- so a board
-- posting located only in "Linz" would have been counted as German. It
-- happened twice ("Deutschland, Österreich, Schweiz und Italien"), neither
-- published, and it would have got worse once this list started naming
-- cities rather than only vouching for a country.
--
-- Names shorter than four characters are excluded: they false-match inside
-- longer words too easily. Names carrying punctuation beyond hyphen and dot
-- are excluded because they are interpolated into a regex downstream.
--
-- Each name carries the spelling and the federal state to publish it under,
-- so a board posting in "Munich, Germany" and a federal one in München land
-- in the same row of the city table instead of two.

with federal as (

    select
        {{ norm('city') }} as city_norm,
        city,
        region,
        count(*)           as postings
    from {{ ref('stg_arbeitsagentur__postings') }}
    where city is not null
      and country = 'DEUTSCHLAND'
    group by 1, 2, 3

),

-- One spelling and one state per normalised name: the one the federal source
-- uses most. Ties fall through to md5 of the spelling rather than the
-- spelling itself, because these names carry umlauts and the two engines are
-- not obliged to sort non-ASCII text the same way. A hex digest sorts the
-- same under any collation.
federal_canonical as (

    select city_norm, city, region
    from (
        select
            *,
            row_number() over (
                partition by city_norm
                order by postings desc, md5(city), md5(coalesce(region, ''))
            ) as spelling_rank
        from federal
    ) ranked
    where spelling_rank = 1

),

-- An exonym resolves to the German name it stands for, and takes that name's
-- state where the federal source knows it. An exonym the federal source has
-- never listed still counts as German, with no state asserted for it.
from_aliases as (

    select
        {{ norm('a.alias') }} as city_norm,
        a.city,
        f.region
    from {{ ref('city_aliases') }} a
    left join federal_canonical f
        on f.city_norm = {{ norm('a.city') }}

),

combined as (

    select city_norm, city, region from federal_canonical
    union all
    select city_norm, city, region from from_aliases
    where city_norm not in (select city_norm from federal_canonical)

)

select city_norm, city, region
from combined
where length(city_norm) >= 4
  and {{ match('city_norm', '^[a-z0-9 .-]+$') }}
