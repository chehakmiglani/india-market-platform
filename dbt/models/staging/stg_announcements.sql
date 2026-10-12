-- news_type groups NSE's ~100 filing categories into what matters for surveillance:
-- could this filing explain an unusual move, or is it routine paperwork?
select
    seq_id,
    symbol,
    announced_at,
    cast(announced_at as date)                                         as announced_date,
    category,
    summary,
    attachment_url,
    case
        when category ilike '%spurt in volume%' or category ilike '%price movement%'
          or category ilike 'clarification%'                            then 'EXCHANGE_QUERY'
        when category ilike '%financial result%' or category ilike 'integrated filing%'
          or category = 'Outcome of Board Meeting'
          or category ilike 'analysts/institutional%' or category = 'Investor Presentation'
          -- quarterly business updates often arrive as plain press releases ("Update for Q2FY27")
          or regexp_matches(summary, '\bQ[1-4]\s?FY\s?\d{2}', 'i')
                                                                        then 'RESULTS'
        when category ilike '%orders/contracts%'                        then 'ORDER_WIN'
        when category in ('Acquisition', 'Amalgamation / Merger', 'Scheme of Arrangement',
                          'Buyback', 'Preferential Issue', 'Qualified Institutional Placement',
                          'Fund raising', 'Disinvestment', 'Open Offer')
          or category ilike '%takeover%'                                then 'CORPORATE_DEAL'
        when category in ('Credit Rating', 'Corporate Insolvency Resolution Process')
          or category ilike 'action(s)%' or category ilike 'pendency of litigation%'
          or category ilike 'granting/withdrawal%'                      then 'REGULATORY_LEGAL'
        when category ilike 'certificate under sebi%' or category ilike '%newspaper%'
          or category in ('Trading Window', 'Structural Digital Database', 'ESOP/ESOS/ESPS',
                          'Shareholders meeting', 'Record Date', 'Extension  of Financial Year',
                          'Loss of Share Certificates', 'Duplicate Share Certificate',
                          'Change in Registrar and Share Transfer Agent', 'Book Closure')
                                                                        then 'ROUTINE'
        else 'OTHER'
    end                                                                as news_type
from {{ source('silver', 'announcements') }}
