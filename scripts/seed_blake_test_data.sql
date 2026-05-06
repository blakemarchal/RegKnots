-- D6.63 — wipe Blake's personal-scope test data and seed a realistic
-- mariner profile so he can experience the product as a real user
-- (and so we can debug Renewal Co-Pilot + Career Path against
-- non-trivial data).
--
-- Idempotent — re-running cleans up any prior seed.
-- Workspace-scoped vessels (MV Blake-Q, Test Wheelhouse) are
-- intentionally preserved.

\set ON_ERROR_STOP on
\set blake_id '57e649b5-e29e-47b4-9bb0-5a30b7a044bc'

BEGIN;

-- ── 1. Clear personal-scope data ───────────────────────────────────────────

DELETE FROM user_credentials WHERE user_id = :'blake_id';
DELETE FROM sea_time_entries WHERE user_id = :'blake_id';
DELETE FROM vessel_documents
  WHERE user_id = :'blake_id'
    AND vessel_id IN (
      SELECT id FROM vessels
      WHERE user_id = :'blake_id' AND workspace_id IS NULL
    );
DELETE FROM vessels
  WHERE user_id = :'blake_id' AND workspace_id IS NULL;


-- ── 2. Seed two personal vessels ──────────────────────────────────────────

INSERT INTO vessels (
    id, user_id, name, vessel_type, gross_tonnage, flag_state,
    route_types, cargo_types, subchapter,
    inspection_certificate_type, manning_requirement,
    additional_details
) VALUES
(
    'd6d63d63-1111-4101-8001-000000000001',
    :'blake_id',
    'M/V Pacific Crossing',
    'Containership',
    850.00,
    'United States',
    ARRAY['near-coastal','coastal']::text[],
    ARRAY['Containers','Hazardous Materials']::text[],
    'I',
    'COI',
    'Master, 1 Mate, 1 AB, 2 OS, 1 Engineer',
    '{"official_number":"OFC-1198347","propulsion":"Diesel","horsepower":"3200","home_port":"Galveston, TX"}'::jsonb
),
(
    'd6d63d63-1111-4101-8001-000000000002',
    :'blake_id',
    'M/V Bay Pioneer',
    'Towing / Tugboat',
    95.00,
    'United States',
    ARRAY['inland','near-coastal']::text[],
    ARRAY[]::text[],
    'M',
    'Subchapter M TSMS',
    'Master, 1 Mate, 1 Deckhand',
    '{"official_number":"OFC-887234","propulsion":"Diesel","horsepower":"1800","home_port":"Houston, TX"}'::jsonb
);


-- ── 3. Seed credentials ───────────────────────────────────────────────────
-- Realistic mariner credential portfolio for a near-coastal Master.
-- All dates anchored relative to 2026-05-06 so the demo is current.

INSERT INTO user_credentials (
    id, user_id, credential_type, title, credential_number,
    issuing_authority, issue_date, expiry_date, notes
) VALUES
-- Primary MMC — 5-year cycle, ~3.5 years remaining
(
    'cdcdcdcd-aaaa-4001-8001-000000000001', :'blake_id', 'mmc',
    'Master of Inland Steam or Motor Vessels of Less Than 1600 GRT; Mate of Near-Coastal Steam or Motor Vessels of Less Than 1600 GRT',
    'MMC-2024-198347', 'USCG National Maritime Center',
    '2024-08-15', '2029-08-15',
    'Endorsements: Master Inland <1600 GRT; Mate NC <1600 GRT.'
),
-- TWIC — 5-year cycle, ~2 years remaining
(
    'cdcdcdcd-aaaa-4001-8001-000000000002', :'blake_id', 'twic',
    'Transportation Worker Identification Credential',
    'T-9876-5432-10', 'TSA',
    '2023-11-12', '2028-11-12',
    NULL
),
-- Medical — 2-year cycle. Approaching renewal in ~16 months — Renewal
-- Co-Pilot card eligibility is gated at 180d so this won't show the
-- AI button yet; expiry banner will. Tightened later if we want to demo
-- the AI card on this row.
(
    'cdcdcdcd-aaaa-4001-8001-000000000003', :'blake_id', 'medical',
    'Merchant Mariner Medical Certificate',
    'MMC-MED-558912', 'USCG NMC Medical Evaluation Branch',
    '2024-09-22', '2026-09-22',
    'Issued without restrictions. CG-719K filed via Regional Exam Center.'
),
-- STCW Officer-of-the-Watch endorsement — 5yr, ~3.5yr remaining
(
    'cdcdcdcd-aaaa-4001-8001-000000000004', :'blake_id', 'stcw',
    'STCW II/1 — Officer in Charge of a Navigational Watch on Vessels of 500 GT or More',
    'STCW-II/1-247831', 'USCG National Maritime Center',
    '2024-08-15', '2029-08-15',
    NULL
),
-- STCW Basic Safety Training — 5yr cycle
(
    'cdcdcdcd-aaaa-4001-8001-000000000005', :'blake_id', 'stcw',
    'Basic Safety Training (BST)',
    'STCW-BST-993421', 'Maritime Professional Training (MPT) — Course-Approved',
    '2024-08-10', '2029-08-10',
    'Personal Survival Techniques, Fire Prevention/Firefighting, Elementary First Aid, PSSR.'
),
-- STCW Advanced Firefighting — 5yr
(
    'cdcdcdcd-aaaa-4001-8001-000000000006', :'blake_id', 'stcw',
    'Advanced Firefighting',
    'STCW-AFF-441290', 'Houston Marine Training Services',
    '2024-08-12', '2029-08-12',
    NULL
),
-- Radar Observer Unlimited — 5yr
(
    'cdcdcdcd-aaaa-4001-8001-000000000007', :'blake_id', 'stcw',
    'Radar Observer Unlimited',
    'ROU-2024-77614', 'Calhoon MEBA Engineering School',
    '2024-08-08', '2029-08-08',
    NULL
),
-- DOT Drug Test Letter — required for MMC issuance/renewal; valid 24mo
-- in NMC practice but no formal expiry on the document itself
(
    'cdcdcdcd-aaaa-4001-8001-000000000008', :'blake_id', 'other',
    'DOT 5-Panel Drug Test Letter',
    'DOT-DT-2024-44829', 'Concentra Medical Center (Houston)',
    '2024-08-05', NULL,
    'Negative result. Required by 46 CFR 16. NMC accepts within 24 months of issuance.'
),
-- Yellow Fever Vaccination — 10yr
(
    'cdcdcdcd-aaaa-4001-8001-000000000009', :'blake_id', 'other',
    'Yellow Fever Vaccination Certificate',
    'YF-VAC-2024-3392', 'Travel Med Galveston',
    '2024-06-18', '2034-06-18',
    'WHO International Certificate of Vaccination (yellow card). Required for Liberia/Marshall Islands port calls.'
);


-- ── 4. Seed sea-time entries ──────────────────────────────────────────────
-- ~6-year career arc OS → AB → 3rd Mate → Mate → Master.
-- Total ~1763 days; last 3 years ~830 days; last 5 years ~1600 days.

INSERT INTO sea_time_entries (
    id, user_id, vessel_id, vessel_name, official_number,
    vessel_type, gross_tonnage, horsepower, propulsion, route_type,
    capacity_served, from_date, to_date, days_on_board,
    employer_name, employer_signed, notes
) VALUES
-- 2020 — entry-level OS on inland tug
(
    'e7e7e7e7-1111-4001-8001-000000000001', :'blake_id', NULL,
    'M/V Galveston Express', 'OFC-447712', 'Towing / Tugboat',
    75.00, '900', 'Diesel', 'Inland',
    'OS', '2020-03-15', '2020-08-30', 169,
    'Galveston Bay Towing LLC', TRUE, NULL
),
(
    'e7e7e7e7-1111-4001-8001-000000000002', :'blake_id', NULL,
    'M/V Galveston Express', 'OFC-447712', 'Towing / Tugboat',
    75.00, '900', 'Diesel', 'Inland',
    'OS', '2020-10-12', '2021-03-04', 144,
    'Galveston Bay Towing LLC', TRUE, NULL
),
-- 2021 — promoted to AB
(
    'e7e7e7e7-1111-4001-8001-000000000003', :'blake_id', NULL,
    'M/V Galveston Express', 'OFC-447712', 'Towing / Tugboat',
    75.00, '900', 'Diesel', 'Inland',
    'AB', '2021-04-18', '2021-09-30', 166,
    'Galveston Bay Towing LLC', TRUE, NULL
),
(
    'e7e7e7e7-1111-4001-8001-000000000004', :'blake_id',
    'd6d63d63-1111-4101-8001-000000000002',
    'M/V Bay Pioneer', 'OFC-887234', 'Towing / Tugboat',
    95.00, '1800', 'Diesel', 'Inland',
    'AB', '2021-11-15', '2022-04-02', 139,
    'Bay Pioneer Marine LLC', TRUE, NULL
),
-- 2022 — moved up to 3rd Mate after sufficient AB time
(
    'e7e7e7e7-1111-4001-8001-000000000005', :'blake_id',
    'd6d63d63-1111-4101-8001-000000000002',
    'M/V Bay Pioneer', 'OFC-887234', 'Towing / Tugboat',
    95.00, '1800', 'Diesel', 'Near-Coastal',
    '3rd Mate', '2022-05-10', '2022-10-15', 159,
    'Bay Pioneer Marine LLC', TRUE, NULL
),
-- First larger vessel — coastal containership 3rd Mate
(
    'e7e7e7e7-1111-4001-8001-000000000006', :'blake_id',
    'd6d63d63-1111-4101-8001-000000000001',
    'M/V Pacific Crossing', 'OFC-1198347', 'Containership',
    850.00, '3200', 'Diesel', 'Coastal',
    '3rd Mate', '2022-12-01', '2023-05-30', 181,
    'Pacific Crossing Lines', TRUE, NULL
),
-- 2023-2024 — promoted to Mate
(
    'e7e7e7e7-1111-4001-8001-000000000007', :'blake_id',
    'd6d63d63-1111-4101-8001-000000000001',
    'M/V Pacific Crossing', 'OFC-1198347', 'Containership',
    850.00, '3200', 'Diesel', 'Near-Coastal',
    'Mate', '2023-07-15', '2023-12-30', 169,
    'Pacific Crossing Lines', TRUE, NULL
),
(
    'e7e7e7e7-1111-4001-8001-000000000008', :'blake_id',
    'd6d63d63-1111-4101-8001-000000000001',
    'M/V Pacific Crossing', 'OFC-1198347', 'Containership',
    850.00, '3200', 'Diesel', 'Near-Coastal',
    'Mate', '2024-02-14', '2024-07-22', 160,
    'Pacific Crossing Lines', TRUE, NULL
),
-- 2024-2025 — Master endorsement granted, sailing inland
(
    'e7e7e7e7-1111-4001-8001-000000000009', :'blake_id',
    'd6d63d63-1111-4101-8001-000000000002',
    'M/V Bay Pioneer', 'OFC-887234', 'Towing / Tugboat',
    95.00, '1800', 'Diesel', 'Inland',
    'Master', '2024-08-25', '2025-01-30', 159,
    'Bay Pioneer Marine LLC', TRUE, NULL
),
(
    'e7e7e7e7-1111-4001-8001-000000000010', :'blake_id',
    'd6d63d63-1111-4101-8001-000000000002',
    'M/V Bay Pioneer', 'OFC-887234', 'Towing / Tugboat',
    95.00, '1800', 'Diesel', 'Near-Coastal',
    'Master', '2025-03-12', '2025-08-15', 157,
    'Bay Pioneer Marine LLC', TRUE, NULL
),
-- 2025-2026 — recent contract back on Pacific Crossing as Mate
(
    'e7e7e7e7-1111-4001-8001-000000000011', :'blake_id',
    'd6d63d63-1111-4101-8001-000000000001',
    'M/V Pacific Crossing', 'OFC-1198347', 'Containership',
    850.00, '3200', 'Diesel', 'Near-Coastal',
    'Mate', '2025-09-22', '2026-02-28', 160,
    'Pacific Crossing Lines', TRUE, NULL
);


-- ── 5. Confirm the seed ────────────────────────────────────────────────────

SELECT
    'credentials' AS table_name,
    COUNT(*) AS rows_seeded
FROM user_credentials WHERE user_id = :'blake_id'
UNION ALL SELECT 'sea_time_entries',
    COUNT(*) FROM sea_time_entries WHERE user_id = :'blake_id'
UNION ALL SELECT 'personal vessels',
    COUNT(*) FROM vessels
    WHERE user_id = :'blake_id' AND workspace_id IS NULL;

COMMIT;
