ALTER TABLE holidays ADD COLUMN source text NOT NULL DEFAULT 'Kerala GAD 2026 G.O.(P)14/2025';
-- Complete the public-office list (not bank-only or restricted holidays).
-- GAD 2026 PDF pages 2-3: https://gad.kerala.gov.in/sites/default/files/inline-files/public-holidays-2026_0.pdf
INSERT INTO holidays(day, name) VALUES
('2026-01-02', 'Mannam Jayanthi'),
('2026-03-20', 'Id-ul-Fitr (moon sighting dependent)'),
('2026-04-02', 'Maundy Thursday'),
('2026-04-14', 'Ambedkar Jayanthi'),
('2026-05-27', 'Bakrid (moon sighting dependent)'),
('2026-06-25', 'Muharram (moon sighting dependent)'),
('2026-08-12', 'Karkadaka Vavu'),
('2026-08-27', 'Third Onam'),
('2026-09-04', 'Sreekrishna Jayanthi'),
('2026-09-21', 'Sree Narayana Guru Samadhi'),
('2026-10-20', 'Mahanavami'),
('2026-10-21', 'Vijayadasami');
-- Public-office list in official GAD Diary 2027, printed pp.181-182.
-- https://gad.kerala.gov.in/sites/default/files/inline-files/diary27.pdf
INSERT INTO holidays(day, name, source)
SELECT day::date, name, 'Kerala GAD Diary 2027 pp.181-182 (draft; moon dates subject to change)'
FROM (VALUES
('2027-01-02', 'Mannam Jayanthi'), ('2027-01-26', 'Republic Day'),
('2027-03-06', 'Maha Sivarathri'), ('2027-03-10', 'Id-ul-Fitr'),
('2027-03-25', 'Maundy Thursday'), ('2027-03-26', 'Good Friday'),
('2027-04-14', 'Ambedkar Jayanthi'), ('2027-04-15', 'Vishu'),
('2027-05-01', 'May Day'), ('2027-05-17', 'Bakrid'),
('2027-06-15', 'Muharram'), ('2027-08-02', 'Karkadaka Vavu'),
('2027-08-24', 'Sreekrishna Jayanthi'), ('2027-08-28', 'Ayyan Kali Jayanthi'),
('2027-09-13', 'Third Onam'), ('2027-09-14', 'Fourth Onam'),
('2027-09-15', 'Sree Narayana Guru Jayanthi'), ('2027-09-22', 'Sree Narayana Guru Samadhi'),
('2027-10-02', 'Gandhi Jayanthi'), ('2027-10-28', 'Deepavali'), ('2027-12-25', 'Christmas'),
-- Listed separately in GAD because they fall on weekends.
('2027-03-28', 'Easter'), ('2027-08-14', 'Milad-i-Sherif'),
('2027-08-15', 'Independence Day'), ('2027-09-11', 'First Onam'),
('2027-09-12', 'Thiruvonam'), ('2027-10-09', 'Mahanavami'), ('2027-10-10', 'Vijayadasami')
) AS verified(day, name);
INSERT INTO holidays(day, name, source) VALUES
('2027-01-01', 'New Year - company holiday', 'Company holiday assumed by the author; not in the GAD list');
