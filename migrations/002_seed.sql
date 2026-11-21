INSERT INTO sla_policies(priority, first_reply_minutes, resolve_minutes) VALUES
('urgent', 120, NULL), ('medium', 270, 1620), ('small', 540, 2700);
INSERT INTO agents(name, email)
SELECT name, 'agent' || ordinality || '@arvo.example'
FROM unnest(ARRAY['Meera', 'Arun', 'Divya', 'Nikhil', 'Anjali', 'Rahul', 'Priya', 'Vivek', 'Sneha']) WITH ORDINALITY AS a(name, ordinality);
-- Initial subset, checked against Kerala GAD 2026 public holidays.
-- https://gad.kerala.gov.in/sites/default/files/inline-files/public-holidays-2026_0.pdf
INSERT INTO holidays(day, name) VALUES
('2026-01-26', 'Republic Day'),
('2026-04-03', 'Good Friday'),
('2026-04-15', 'Vishu'),
('2026-05-01', 'May Day'),
('2026-08-15', 'Independence Day'),
('2026-08-25', 'First Onam'),
('2026-08-26', 'Thiruvonam'),
('2026-08-28', 'Sree Narayana Guru Jayanthi / Ayyankali Jayanthi'),
('2026-10-02', 'Gandhi Jayanthi'),
('2026-12-25', 'Christmas');
