-- A reference list of German place names, derived from the federal database.
--
-- The second source states no country, only free-text location, so something
-- has to decide whether "Dusseldorf" and "Manchester" belong in a dataset
-- about Germany. Rather than hand-maintain a list or call a geocoder, we use
-- the place names the federal job database itself reports -- tens of
-- thousands of postings across the country. The dataset validates itself.
--
-- Names shorter than four characters are excluded: they false-match inside
-- longer words too easily. Names carrying punctuation beyond hyphen and dot
-- are excluded because they are interpolated into a regex downstream.

with from_federal as (

    select distinct {{ norm('city') }} as city_norm
    from {{ ref('stg_arbeitsagentur__postings') }}
    where city is not null

),

from_aliases as (

    select distinct {{ norm('alias') }} as city_norm
    from {{ ref('city_aliases') }}

),

combined as (

    select city_norm from from_federal
    union
    select city_norm from from_aliases

)

select city_norm
from combined
where length(city_norm) >= 4
  and {{ match('city_norm', '^[a-z0-9 .-]+$') }}
