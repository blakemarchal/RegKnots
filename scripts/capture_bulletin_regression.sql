-- Sprint B2 regression capture: run BEFORE rollback
-- Produces two sets:
--   1. known-good regression — bulletins whose canonical ID was correct
--   2. mislabel regression — bulletins whose subject starts ALCGENL/ACN/etc.
--      but were filed under an ALCOAST/MSIB/NVIC section_number (the bug)

\pset format unaligned
\pset fieldsep E'\t'
\pset tuples_only on

-- KNOWN-GOOD SET (should be re-accepted after filter fix)
\echo '=== known_good ==='
SELECT
  substring(full_text from 'bulletins/([0-9a-f]+)') AS gd_id,
  section_number, section_title, published_date
FROM regulations
WHERE source = 'uscg_bulletin' AND chunk_index = 0
  AND (
    section_number LIKE 'MSIB%'
    OR section_number LIKE 'NMC Announcement%'
    OR section_number LIKE 'NVIC%'
    OR section_number LIKE 'CG-%'
  )
ORDER BY section_number;

-- MISLABEL SET (should be re-labeled or rejected; NEVER re-accepted under the old wrong canonical ID)
\echo '=== mislabeled ==='
SELECT
  substring(full_text from 'bulletins/([0-9a-f]+)') AS gd_id,
  section_number AS prior_section_number,
  section_title AS actual_subject,
  published_date
FROM regulations
WHERE source = 'uscg_bulletin' AND chunk_index = 0
  AND (
    section_title ILIKE 'ALCGENL%'
    OR section_title ILIKE 'ACN %'
    OR section_title ILIKE 'COMDTNOTE%'
  )
ORDER BY published_date;
